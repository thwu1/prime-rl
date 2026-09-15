/*
 * cstore.c - CStore binary codec reference implementation
 * Custom binary serialization format for JSON data.
 *
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>

/* ======================== CRC32 ======================== */
static uint32_t crc_t[256];
static void crc_init(void){
    for(int i=0;i<256;i++){
        uint32_t c=i;
        for(int j=0;j<8;j++) c=(c&1)?0xEDB88320u^(c>>1):c>>1;
        crc_t[i]=c;
    }
}
static uint32_t get_crc_seed(void){
    uint32_t s=~0u;
    const char*salt=getenv("CSTORE_SALT");
    if(salt&&salt[0]){
        for(int i=0;salt[i];i++)
            s^=((uint32_t)(unsigned char)salt[i])<<((i%4)*8);
    }
    return s;
}
static uint32_t crc32(const uint8_t*d,size_t n){
    uint32_t c=get_crc_seed();
    for(size_t i=0;i<n;i++) c=crc_t[(c^d[i])&0xFF]^(c>>8);
    return ~c;
}

/* ======================== Buffer ======================== */
typedef struct{uint8_t*d;size_t n,c;}Buf;
static void bp(Buf*b,uint8_t v){
    if(b->n>=b->c){b->c=b->c?b->c*2:256;b->d=realloc(b->d,b->c);}
    b->d[b->n++]=v;
}
static void bw(Buf*b,const void*p,size_t l){
    const uint8_t*s=p;for(size_t i=0;i<l;i++)bp(b,s[i]);
}

/* ======================== Varint ======================== */
static void wvar(Buf*b,uint64_t v){
    do{uint8_t x=v&0x7F;v>>=7;if(v)x|=0x80;bp(b,x);}while(v);
}
static uint64_t rvar(const uint8_t*d,size_t len,size_t*p){
    uint64_t r=0;int s=0;
    while(*p<len){
        uint8_t x=d[(*p)++];
        r|=(uint64_t)(x&0x7F)<<s;
        if(!(x&0x80))return r;
        s+=7;if(s>=64){fprintf(stderr,"varint overflow\n");exit(1);}
    }
    fprintf(stderr,"truncated varint\n");exit(1);
}

/* ======================== Zigzag ======================== */
static uint64_t zzenc(int64_t n){return(uint64_t)((n<<1)^(n>>63));}
static int64_t zzdec(uint64_t n){return(int64_t)((n>>1)^-(int64_t)(n&1));}

/* ======================== JSON Value ======================== */
enum{T_NULL,T_BOOL,T_INT,T_FLOAT,T_STR,T_ARR,T_OBJ};
typedef struct Val Val;
typedef struct{char*k;size_t kl;Val*v;}KV;
struct Val{
    int t;
    union{
        int b;
        int64_t i;
        double f;
        struct{char*s;size_t l;}str;
        struct{Val**a;size_t n;}arr;
        struct{KV*p;size_t n;}obj;
    }u;
};
static Val*vnew(int t){Val*v=calloc(1,sizeof(Val));v->t=t;return v;}
static void vfree(Val*v){
    if(!v)return;
    if(v->t==T_STR)free(v->u.str.s);
    else if(v->t==T_ARR){
        for(size_t i=0;i<v->u.arr.n;i++)vfree(v->u.arr.a[i]);
        free(v->u.arr.a);
    }else if(v->t==T_OBJ){
        for(size_t i=0;i<v->u.obj.n;i++){free(v->u.obj.p[i].k);vfree(v->u.obj.p[i].v);}
        free(v->u.obj.p);
    }
    free(v);
}

/* ======================== Read stdin ======================== */
static uint8_t*read_all(size_t*len){
    Buf b={0};int c;
    while((c=fgetc(stdin))!=EOF)bp(&b,(uint8_t)c);
    *len=b.n;return b.d;
}

/* ======================== JSON Parser ======================== */
typedef struct{const char*s;size_t p,n;}JP;
static void jskip(JP*j){
    while(j->p<j->n&&(j->s[j->p]==' '||j->s[j->p]=='\t'||
          j->s[j->p]=='\n'||j->s[j->p]=='\r'))j->p++;
}
static char jpeek(JP*j){jskip(j);return j->p<j->n?j->s[j->p]:0;}
static char jnext(JP*j){jskip(j);return j->p<j->n?j->s[j->p++]:0;}
static int jmatch(JP*j,const char*w){
    size_t l=strlen(w);
    if(j->p+l<=j->n&&!memcmp(j->s+j->p,w,l)){j->p+=l;return 1;}
    return 0;
}
static int hexd(char c){
    if(c>='0'&&c<='9')return c-'0';
    if(c>='a'&&c<='f')return c-'a'+10;
    if(c>='A'&&c<='F')return c-'A'+10;
    return-1;
}
static void utf8_enc(Buf*b,uint32_t cp){
    if(cp<0x80)bp(b,(uint8_t)cp);
    else if(cp<0x800){bp(b,0xC0|(cp>>6));bp(b,0x80|(cp&0x3F));}
    else if(cp<0x10000){bp(b,0xE0|(cp>>12));bp(b,0x80|((cp>>6)&0x3F));bp(b,0x80|(cp&0x3F));}
    else{bp(b,0xF0|(cp>>18));bp(b,0x80|((cp>>12)&0x3F));bp(b,0x80|((cp>>6)&0x3F));bp(b,0x80|(cp&0x3F));}
}

static Val*jparse(JP*j);

static Val*jparse_str(JP*j){
    if(jnext(j)!='"'){fprintf(stderr,"expected '\"'\n");exit(1);}
    Buf b={0};
    while(j->p<j->n&&j->s[j->p]!='"'){
        if(j->s[j->p]=='\\'){
            j->p++;
            if(j->p>=j->n){fprintf(stderr,"unexpected end in string\n");exit(1);}
            char c=j->s[j->p++];
            switch(c){
                case'"':bp(&b,'"');break;
                case'\\':bp(&b,'\\');break;
                case'/':bp(&b,'/');break;
                case'b':bp(&b,'\b');break;
                case'f':bp(&b,'\f');break;
                case'n':bp(&b,'\n');break;
                case'r':bp(&b,'\r');break;
                case't':bp(&b,'\t');break;
                case'u':{
                    if(j->p+4>j->n){fprintf(stderr,"bad \\u\n");exit(1);}
                    uint32_t cp=0;
                    for(int i=0;i<4;i++){
                        int d=hexd(j->s[j->p++]);
                        if(d<0){fprintf(stderr,"bad hex\n");exit(1);}
                        cp=(cp<<4)|d;
                    }
                    if(cp>=0xD800&&cp<=0xDBFF){
                        if(j->p+6<=j->n&&j->s[j->p]=='\\'&&j->s[j->p+1]=='u'){
                            j->p+=2;uint32_t lo=0;
                            for(int i=0;i<4;i++){
                                int d=hexd(j->s[j->p++]);
                                if(d<0){fprintf(stderr,"bad hex\n");exit(1);}
                                lo=(lo<<4)|d;
                            }
                            if(lo>=0xDC00&&lo<=0xDFFF)
                                cp=0x10000+((cp-0xD800)<<10)+(lo-0xDC00);
                            else{fprintf(stderr,"bad surrogate pair\n");exit(1);}
                        }else{fprintf(stderr,"lone high surrogate\n");exit(1);}
                    }
                    utf8_enc(&b,cp);
                    break;
                }
                default:fprintf(stderr,"bad escape \\%c\n",c);exit(1);
            }
        }else{
            bp(&b,(uint8_t)j->s[j->p++]);
        }
    }
    if(j->p>=j->n){fprintf(stderr,"unterminated string\n");exit(1);}
    j->p++; /* closing quote */
    bp(&b,0);
    Val*v=vnew(T_STR);v->u.str.l=b.n-1;v->u.str.s=(char*)b.d;
    return v;
}

static Val*jparse_num(JP*j){
    const char*start=j->s+j->p;
    int is_float=0;
    if(j->p<j->n&&j->s[j->p]=='-')j->p++;
    if(j->p>=j->n||j->s[j->p]<'0'||j->s[j->p]>'9'){fprintf(stderr,"bad number\n");exit(1);}
    while(j->p<j->n&&j->s[j->p]>='0'&&j->s[j->p]<='9')j->p++;
    if(j->p<j->n&&j->s[j->p]=='.'){
        is_float=1;j->p++;
        while(j->p<j->n&&j->s[j->p]>='0'&&j->s[j->p]<='9')j->p++;
    }
    if(j->p<j->n&&(j->s[j->p]=='e'||j->s[j->p]=='E')){
        is_float=1;j->p++;
        if(j->p<j->n&&(j->s[j->p]=='+'||j->s[j->p]=='-'))j->p++;
        while(j->p<j->n&&j->s[j->p]>='0'&&j->s[j->p]<='9')j->p++;
    }
    size_t len=(j->s+j->p)-start;
    char*tmp=malloc(len+1);memcpy(tmp,start,len);tmp[len]=0;

    if(!is_float){
        errno=0;
        char*end;
        long long ll=strtoll(tmp,&end,10);
        if(*end==0&&errno!=ERANGE){
            free(tmp);
            Val*v=vnew(T_INT);v->u.i=(int64_t)ll;return v;
        }
        is_float=1;
    }
    double d=strtod(tmp,NULL);
    free(tmp);
    Val*v=vnew(T_FLOAT);v->u.f=d;return v;
}

static int kv_cmp(const void*a,const void*b){
    const KV*ka=a,*kb=b;
    size_t ml=ka->kl<kb->kl?ka->kl:kb->kl;
    int c=memcmp(ka->k,kb->k,ml);
    if(c)return c;
    return(ka->kl>kb->kl)-(ka->kl<kb->kl);
}

static Val*jparse(JP*j){
    char c=jpeek(j);
    if(c=='n'){if(jmatch(j,"null"))return vnew(T_NULL);goto err;}
    if(c=='t'){if(jmatch(j,"true")){Val*v=vnew(T_BOOL);v->u.b=1;return v;}goto err;}
    if(c=='f'){if(jmatch(j,"false")){Val*v=vnew(T_BOOL);v->u.b=0;return v;}goto err;}
    if(c=='"')return jparse_str(j);
    if(c=='-'||(c>='0'&&c<='9'))return jparse_num(j);
    if(c=='['){
        jnext(j);Val*v=vnew(T_ARR);
        if(jpeek(j)==']'){jnext(j);return v;}
        size_t cap=8;v->u.arr.a=malloc(cap*sizeof(Val*));
        for(;;){
            if(v->u.arr.n>=cap){cap*=2;v->u.arr.a=realloc(v->u.arr.a,cap*sizeof(Val*));}
            v->u.arr.a[v->u.arr.n++]=jparse(j);
            if(jpeek(j)==','){jnext(j);continue;}
            break;
        }
        if(jnext(j)!=']'){fprintf(stderr,"expected ']'\n");exit(1);}
        return v;
    }
    if(c=='{'){
        jnext(j);Val*v=vnew(T_OBJ);
        if(jpeek(j)=='}'){jnext(j);return v;}
        size_t cap=8;v->u.obj.p=malloc(cap*sizeof(KV));
        for(;;){
            if(v->u.obj.n>=cap){cap*=2;v->u.obj.p=realloc(v->u.obj.p,cap*sizeof(KV));}
            Val*ks=jparse_str(j);
            if(jnext(j)!=':'){fprintf(stderr,"expected ':'\n");exit(1);}
            Val*val=jparse(j);
            /* Duplicate keys: last wins */
            int found=-1;
            for(size_t i=0;i<v->u.obj.n;i++){
                if(v->u.obj.p[i].kl==ks->u.str.l&&!memcmp(v->u.obj.p[i].k,ks->u.str.s,ks->u.str.l)){
                    found=(int)i;break;
                }
            }
            if(found>=0){
                vfree(v->u.obj.p[found].v);
                v->u.obj.p[found].v=val;
                vfree(ks);
            }else{
                v->u.obj.p[v->u.obj.n].k=ks->u.str.s;
                v->u.obj.p[v->u.obj.n].kl=ks->u.str.l;
                v->u.obj.p[v->u.obj.n].v=val;
                v->u.obj.n++;
                ks->u.str.s=NULL;
                vfree(ks);
            }
            if(jpeek(j)==','){jnext(j);continue;}
            break;
        }
        if(jnext(j)!='}'){fprintf(stderr,"expected '}'\n");exit(1);}
        qsort(v->u.obj.p,v->u.obj.n,sizeof(KV),kv_cmp);
        return v;
    }
err:
    fprintf(stderr,"unexpected char '%c' (0x%02x)\n",c,(unsigned char)c);exit(1);
}

/* ======================== Encoder ======================== */
static void encode_val(Buf*b,Val*v){
    switch(v->t){
        case T_NULL:bp(b,0x00);break;
        case T_BOOL:bp(b,v->u.b?0x02:0x01);break;
        case T_INT:bp(b,0x03);wvar(b,zzenc(v->u.i));break;
        case T_FLOAT:{
            bp(b,0x04);
            double d=v->u.f;
            if(d==0.0)d=0.0; /* normalize -0 to +0 */
            uint64_t bits;memcpy(&bits,&d,8);
            for(int i=7;i>=0;i--)bp(b,(uint8_t)(bits>>(i*8)));
            break;
        }
        case T_STR:
            bp(b,0x05);wvar(b,(uint64_t)v->u.str.l);
            bw(b,v->u.str.s,v->u.str.l);break;
        case T_ARR:
            bp(b,0x06);wvar(b,(uint64_t)v->u.arr.n);
            for(size_t i=0;i<v->u.arr.n;i++)encode_val(b,v->u.arr.a[i]);
            break;
        case T_OBJ:
            bp(b,0x07);wvar(b,(uint64_t)v->u.obj.n);
            for(size_t i=0;i<v->u.obj.n;i++){
                wvar(b,(uint64_t)v->u.obj.p[i].kl);
                bw(b,v->u.obj.p[i].k,v->u.obj.p[i].kl);
                encode_val(b,v->u.obj.p[i].v);
            }
            break;
    }
}

static void cmd_encode(void){
    size_t ilen;uint8_t*input=read_all(&ilen);
    JP jp={(const char*)input,0,ilen};
    Val*root=jparse(&jp);
    jskip(&jp);
    if(jp.p!=jp.n){fprintf(stderr,"trailing content after JSON value\n");exit(1);}
    Buf out={0};
    bw(&out,"CST\x01",4);
    encode_val(&out,root);
    uint32_t c=crc32(out.d,out.n);
    bp(&out,(c>>24)&0xFF);bp(&out,(c>>16)&0xFF);
    bp(&out,(c>>8)&0xFF);bp(&out,c&0xFF);
    fwrite(out.d,1,out.n,stdout);
    vfree(root);free(input);free(out.d);
}

/* ======================== Decoder ======================== */
static Val*decode_val(const uint8_t*d,size_t len,size_t*p){
    if(*p>=len){fprintf(stderr,"unexpected end of data\n");exit(1);}
    uint8_t tag=d[(*p)++];
    switch(tag){
        case 0x00:return vnew(T_NULL);
        case 0x01:{Val*v=vnew(T_BOOL);v->u.b=0;return v;}
        case 0x02:{Val*v=vnew(T_BOOL);v->u.b=1;return v;}
        case 0x03:{
            uint64_t zz=rvar(d,len,p);
            Val*v=vnew(T_INT);v->u.i=zzdec(zz);return v;
        }
        case 0x04:{
            if(*p+8>len){fprintf(stderr,"truncated float\n");exit(1);}
            uint64_t bits=0;
            for(int i=0;i<8;i++)bits=(bits<<8)|d[(*p)++];
            Val*v=vnew(T_FLOAT);memcpy(&v->u.f,&bits,8);return v;
        }
        case 0x05:{
            uint64_t sl=rvar(d,len,p);
            if(*p+sl>len){fprintf(stderr,"truncated string\n");exit(1);}
            Val*v=vnew(T_STR);
            v->u.str.s=malloc(sl+1);memcpy(v->u.str.s,d+*p,sl);
            v->u.str.s[sl]=0;v->u.str.l=sl;*p+=sl;return v;
        }
        case 0x06:{
            uint64_t cnt=rvar(d,len,p);
            Val*v=vnew(T_ARR);
            if(cnt>0){v->u.arr.a=malloc(cnt*sizeof(Val*));}
            v->u.arr.n=cnt;
            for(uint64_t i=0;i<cnt;i++)v->u.arr.a[i]=decode_val(d,len,p);
            return v;
        }
        case 0x07:{
            uint64_t cnt=rvar(d,len,p);
            Val*v=vnew(T_OBJ);
            if(cnt>0){v->u.obj.p=malloc(cnt*sizeof(KV));}
            v->u.obj.n=cnt;
            for(uint64_t i=0;i<cnt;i++){
                uint64_t kl=rvar(d,len,p);
                if(*p+kl>len){fprintf(stderr,"truncated key\n");exit(1);}
                v->u.obj.p[i].k=malloc(kl+1);
                memcpy(v->u.obj.p[i].k,d+*p,kl);
                v->u.obj.p[i].k[kl]=0;v->u.obj.p[i].kl=kl;
                *p+=kl;
                v->u.obj.p[i].v=decode_val(d,len,p);
            }
            return v;
        }
        default:fprintf(stderr,"unknown tag 0x%02x\n",tag);exit(1);
    }
}

/* ======================== JSON Output ======================== */
static void str_out(FILE*f,const char*s,size_t l){
    fputc('"',f);
    for(size_t i=0;i<l;i++){
        unsigned char c=(unsigned char)s[i];
        switch(c){
            case'"':fputs("\\\"",f);break;
            case'\\':fputs("\\\\",f);break;
            case'\b':fputs("\\b",f);break;
            case'\f':fputs("\\f",f);break;
            case'\n':fputs("\\n",f);break;
            case'\r':fputs("\\r",f);break;
            case'\t':fputs("\\t",f);break;
            default:
                if(c<0x20)fprintf(f,"\\u%04x",c);
                else fputc(c,f);
        }
    }
    fputc('"',f);
}

static void json_out(FILE*f,Val*v,int indent){
    int sp=indent*2;
    switch(v->t){
        case T_NULL:fputs("null",f);break;
        case T_BOOL:fputs(v->u.b?"true":"false",f);break;
        case T_INT:fprintf(f,"%lld",(long long)v->u.i);break;
        case T_FLOAT:{
            char buf[64];
            snprintf(buf,sizeof(buf),"%.17g",v->u.f);
            if(!strchr(buf,'.')&&!strchr(buf,'e')&&!strchr(buf,'E'))
                strcat(buf,".0");
            fputs(buf,f);
            break;
        }
        case T_STR:str_out(f,v->u.str.s,v->u.str.l);break;
        case T_ARR:
            if(v->u.arr.n==0){fputs("[]",f);break;}
            fputs("[\n",f);
            for(size_t i=0;i<v->u.arr.n;i++){
                fprintf(f,"%*s",sp+2,"");
                json_out(f,v->u.arr.a[i],indent+1);
                if(i+1<v->u.arr.n)fputc(',',f);
                fputc('\n',f);
            }
            fprintf(f,"%*s]",sp,"");
            break;
        case T_OBJ:
            if(v->u.obj.n==0){fputs("{}",f);break;}
            fputs("{\n",f);
            for(size_t i=0;i<v->u.obj.n;i++){
                fprintf(f,"%*s",sp+2,"");
                str_out(f,v->u.obj.p[i].k,v->u.obj.p[i].kl);
                fputs(": ",f);
                json_out(f,v->u.obj.p[i].v,indent+1);
                if(i+1<v->u.obj.n)fputc(',',f);
                fputc('\n',f);
            }
            fprintf(f,"%*s}",sp,"");
            break;
    }
}

/* ======================== Info helpers ======================== */
static size_t count_vals(Val*v){
    size_t c=1;
    if(v->t==T_ARR)for(size_t i=0;i<v->u.arr.n;i++)c+=count_vals(v->u.arr.a[i]);
    if(v->t==T_OBJ)for(size_t i=0;i<v->u.obj.n;i++)c+=count_vals(v->u.obj.p[i].v);
    return c;
}
static size_t max_depth(Val*v){
    size_t md=1;
    if(v->t==T_ARR){for(size_t i=0;i<v->u.arr.n;i++){
        size_t d=1+max_depth(v->u.arr.a[i]);if(d>md)md=d;}}
    if(v->t==T_OBJ){for(size_t i=0;i<v->u.obj.n;i++){
        size_t d=1+max_depth(v->u.obj.p[i].v);if(d>md)md=d;}}
    return md;
}
static const char*type_name(int t){
    switch(t){
        case T_NULL:return"null";case T_BOOL:return"boolean";
        case T_INT:return"integer";case T_FLOAT:return"float";
        case T_STR:return"string";case T_ARR:return"array";
        case T_OBJ:return"object";
    }
    return"unknown";
}

/* ======================== Commands ======================== */
static void cmd_decode(void){
    size_t ilen;uint8_t*input=read_all(&ilen);
    if(ilen<9){fprintf(stderr,"file too small\n");exit(1);}
    if(memcmp(input,"CST\x01",4)){fprintf(stderr,"bad magic\n");exit(1);}
    uint32_t stored=(uint32_t)input[ilen-4]<<24|(uint32_t)input[ilen-3]<<16|
                    (uint32_t)input[ilen-2]<<8|input[ilen-1];
    uint32_t calc=crc32(input,ilen-4);
    if(stored!=calc){fprintf(stderr,"CRC mismatch\n");exit(1);}
    size_t pos=4;
    Val*root=decode_val(input,ilen-4,&pos);
    if(pos!=ilen-4){fprintf(stderr,"trailing data in CStore\n");exit(1);}
    json_out(stdout,root,0);
    fputc('\n',stdout);
    vfree(root);free(input);
}

static void cmd_info(void){
    size_t ilen;uint8_t*input=read_all(&ilen);
    if(ilen<9){fprintf(stderr,"file too small\n");exit(1);}
    if(memcmp(input,"CST\x01",4)){fprintf(stderr,"bad magic\n");exit(1);}
    uint32_t stored=(uint32_t)input[ilen-4]<<24|(uint32_t)input[ilen-3]<<16|
                    (uint32_t)input[ilen-2]<<8|input[ilen-1];
    uint32_t calc=crc32(input,ilen-4);
    size_t pos=4;
    Val*root=decode_val(input,ilen-4,&pos);
    printf("CStore v1\n");
    printf("Size: %zu bytes\n",ilen);
    printf("Root: %s\n",type_name(root->t));
    printf("Values: %zu\n",count_vals(root));
    printf("Depth: %zu\n",max_depth(root));
    printf("CRC32: %08x\n",calc);
    printf("Status: %s\n",stored==calc?"OK":"INVALID");
    vfree(root);free(input);
}

int main(int argc,char**argv){
    crc_init();
    if(argc!=2){fprintf(stderr,"Usage: %s <encode|decode|info>\n",argv[0]);return 1;}
    if(!strcmp(argv[1],"encode"))cmd_encode();
    else if(!strcmp(argv[1],"decode"))cmd_decode();
    else if(!strcmp(argv[1],"info"))cmd_info();
    else{fprintf(stderr,"Unknown command: %s\n",argv[1]);return 1;}
    return 0;
}
