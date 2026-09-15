// polytool - polynomial arithmetic over Z/pZ using NTT
// Binary format: 4B magic "POLY" | 4B prime LE | 4B count LE | coefficients LE u32
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <string>
#include <algorithm>
using namespace std;
typedef unsigned int u32;
typedef unsigned long long u64;

static u32 MOD = 998244353;
static const u32 GPRIM = 3;
static const char MAGIC[4] = {'P','O','L','Y'};

u32 pw(u32 a, u32 b, u32 m){
    u32 r=1; a%=m;
    while(b>0){if(b&1)r=(u64)r*a%m;a=(u64)a*a%m;b>>=1;}
    return r;
}

void ntt(vector<u32>&a,bool inv){
    int n=a.size();
    for(int i=1,j=0;i<n;i++){
        int bit=n>>1;
        for(;j&bit;bit>>=1)j^=bit;
        j^=bit;
        if(i<j)swap(a[i],a[j]);
    }
    for(int len=2;len<=n;len<<=1){
        u32 w=inv?pw(GPRIM,MOD-1-(MOD-1)/len,MOD):pw(GPRIM,(MOD-1)/len,MOD);
        for(int i=0;i<n;i+=len){
            u32 wn=1;
            for(int j=0;j<len/2;j++){
                u32 u=a[i+j],v=(u64)a[i+j+len/2]*wn%MOD;
                a[i+j]=(u+v)%MOD;
                a[i+j+len/2]=(u-v+MOD)%MOD;
                wn=(u64)wn*w%MOD;
            }
        }
    }
    if(inv){
        u32 inv_n=pw(n,MOD-2,MOD);
        for(auto&x:a)x=(u64)x*inv_n%MOD;
    }
}

vector<u32> pmul(const vector<u32>&a,const vector<u32>&b,int trunc=-1){
    int la=a.size(),lb=b.size(),rl=la+lb-1;
    if(trunc<0)trunc=rl;
    int n=1;
    while(n<la+lb)n<<=1;
    vector<u32>fa(n,0),fb(n,0);
    copy(a.begin(),a.end(),fa.begin());
    copy(b.begin(),b.end(),fb.begin());
    ntt(fa,false);ntt(fb,false);
    for(int i=0;i<n;i++)fa[i]=(u64)fa[i]*fb[i]%MOD;
    ntt(fa,true);
    vector<u32>res(trunc,0);
    for(int i=0;i<min(rl,trunc);i++)res[i]=fa[i];
    return res;
}

vector<u32> pinv(const vector<u32>&f,int m){
    vector<u32>h={pw(f[0],MOD-2,MOD)};
    int cur=1;
    while(cur<m){
        cur<<=1;
        int fl=min((int)f.size(),cur);
        vector<u32>ft(cur,0);
        copy(f.begin(),f.begin()+fl,ft.begin());
        auto fh=pmul(ft,h,cur);
        vector<u32>neg(cur);
        for(int i=0;i<cur;i++)neg[i]=(MOD-fh[i])%MOD;
        neg[0]=(neg[0]+2)%MOD;
        h=pmul(h,neg,cur);
    }
    h.resize(m);
    return h;
}

bool read_poly(const char*path,u32&prime,vector<u32>&coeffs){
    FILE*fp=fopen(path,"rb");
    if(!fp){fprintf(stderr,"Error: cannot open '%s'\n",path);return false;}
    char mag[4];
    if(fread(mag,1,4,fp)!=4||memcmp(mag,MAGIC,4)!=0){
        fprintf(stderr,"Error: invalid file format in '%s'\n",path);fclose(fp);return false;}
    u32 hdr[2];
    if(fread(hdr,4,2,fp)!=2){fprintf(stderr,"Error: truncated header in '%s'\n",path);fclose(fp);return false;}
    prime=hdr[0];
    u32 cnt=hdr[1];
    coeffs.resize(cnt);
    if(cnt>0&&fread(coeffs.data(),4,cnt,fp)!=cnt){
        fprintf(stderr,"Error: truncated data in '%s'\n",path);fclose(fp);return false;}
    fclose(fp);
    return true;
}

bool write_poly(const char*path,u32 prime,const vector<u32>&coeffs){
    FILE*fp=fopen(path,"wb");
    if(!fp){fprintf(stderr,"Error: cannot write '%s'\n",path);return false;}
    fwrite(MAGIC,1,4,fp);
    u32 hdr[2]={prime,(u32)coeffs.size()};
    fwrite(hdr,4,2,fp);
    if(!coeffs.empty())fwrite(coeffs.data(),4,coeffs.size(),fp);
    fclose(fp);
    return true;
}

void usage(){
    printf("polytool - polynomial arithmetic over Z/pZ\n\n");
    printf("Commands:\n");
    printf("  help                                Show this help\n");
    printf("  info <file>                         Show polynomial metadata\n");
    printf("  dump <file>                         Print all coefficients\n");
    printf("  import <txt> -o <bin> [-p <prime>]  Text to binary\n");
    printf("  mul <a> <b> -o <out> [-n N]         Multiply [truncate to N terms]\n");
    printf("  inv <a> -o <out> -n <N>             Multiplicative inverse mod x^N\n");
    printf("  add <a> <b> -o <out>                Add polynomials\n");
    printf("  scale <a> <scalar> -o <out>         Scalar multiplication\n");
    printf("  eval <file> <x>                     Evaluate at point x\n");
}

const char*find_opt(int argc,char**argv,const char*opt){
    for(int i=2;i<argc-1;i++)if(strcmp(argv[i],opt)==0)return argv[i+1];
    return nullptr;
}
int find_int_opt(int argc,char**argv,const char*opt,int def){
    const char*v=find_opt(argc,argv,opt);
    return v?atoi(v):def;
}

int main(int argc,char**argv){
    if(argc<2){usage();return 1;}
    string cmd=argv[1];

    if(cmd=="help"||cmd=="--help"||cmd=="-h"){usage();return 0;}

    if(cmd=="info"){
        if(argc<3){fprintf(stderr,"Usage: polytool info <file>\n");return 1;}
        u32 p;vector<u32>c;
        if(!read_poly(argv[2],p,c))return 1;
        printf("Prime:        %u\n",p);
        printf("Coefficients: %u\n",(u32)c.size());
        if(!c.empty()){
            printf("c[0]:         %u\n",c[0]);
            if(c.size()>1)printf("c[1]:         %u\n",c[1]);
            if(c.size()>2)printf("c[%u]:      %u\n",(u32)c.size()-1,c.back());
        }
        return 0;
    }

    if(cmd=="dump"){
        if(argc<3){fprintf(stderr,"Usage: polytool dump <file>\n");return 1;}
        u32 p;vector<u32>c;
        if(!read_poly(argv[2],p,c))return 1;
        for(auto x:c)printf("%u\n",x);
        return 0;
    }

    if(cmd=="import"){
        if(argc<3){fprintf(stderr,"Usage: polytool import <txt> -o <bin> [-p <prime>]\n");return 1;}
        const char*out=find_opt(argc,argv,"-o");
        if(!out){fprintf(stderr,"Error: -o <output> required\n");return 1;}
        u32 prime=(u32)find_int_opt(argc,argv,"-p",998244353);
        const char*txt=nullptr;
        for(int i=2;i<argc;i++){
            if(strcmp(argv[i],"-p")==0||strcmp(argv[i],"-o")==0){i++;continue;}
            txt=argv[i];break;
        }
        if(!txt){fprintf(stderr,"Error: no input text file\n");return 1;}
        FILE*fp=fopen(txt,"r");
        if(!fp){fprintf(stderr,"Error: cannot open '%s'\n",txt);return 1;}
        vector<u32>coeffs;
        u32 v;
        while(fscanf(fp,"%u",&v)==1)coeffs.push_back(v);
        fclose(fp);
        MOD=prime;
        write_poly(out,prime,coeffs);
        printf("Imported %u coefficients (prime=%u)\n",(u32)coeffs.size(),prime);
        return 0;
    }

    if(cmd=="mul"){
        if(argc<4){fprintf(stderr,"Usage: polytool mul <a> <b> -o <out> [-n N]\n");return 1;}
        const char*out=find_opt(argc,argv,"-o");
        if(!out){fprintf(stderr,"Error: -o required\n");return 1;}
        int trunc=find_int_opt(argc,argv,"-n",-1);
        u32 pa,pb;vector<u32>a,b;
        if(!read_poly(argv[2],pa,a)||!read_poly(argv[3],pb,b))return 1;
        if(pa!=pb){fprintf(stderr,"Error: prime mismatch (%u vs %u)\n",pa,pb);return 1;}
        MOD=pa;
        auto r=pmul(a,b,trunc);
        write_poly(out,pa,r);
        printf("Product: %u coefficients\n",(u32)r.size());
        return 0;
    }

    if(cmd=="inv"){
        if(argc<3){fprintf(stderr,"Usage: polytool inv <a> -o <out> -n <N>\n");return 1;}
        const char*out=find_opt(argc,argv,"-o");
        int n=find_int_opt(argc,argv,"-n",-1);
        if(!out||n<=0){fprintf(stderr,"Error: -o and -n (positive) required\n");return 1;}
        u32 pa;vector<u32>a;
        if(!read_poly(argv[2],pa,a))return 1;
        MOD=pa;
        auto r=pinv(a,n);
        write_poly(out,pa,r);
        printf("Inverse: %u coefficients\n",(u32)r.size());
        return 0;
    }

    if(cmd=="add"){
        if(argc<4){fprintf(stderr,"Usage: polytool add <a> <b> -o <out>\n");return 1;}
        const char*out=find_opt(argc,argv,"-o");
        if(!out){fprintf(stderr,"Error: -o required\n");return 1;}
        u32 pa,pb;vector<u32>a,b;
        if(!read_poly(argv[2],pa,a)||!read_poly(argv[3],pb,b))return 1;
        if(pa!=pb){fprintf(stderr,"Error: prime mismatch\n");return 1;}
        MOD=pa;
        int m=max(a.size(),b.size());
        a.resize(m,0);b.resize(m,0);
        for(int i=0;i<m;i++)a[i]=(a[i]+b[i])%MOD;
        write_poly(out,pa,a);
        printf("Sum: %u coefficients\n",m);
        return 0;
    }

    if(cmd=="scale"){
        if(argc<4){fprintf(stderr,"Usage: polytool scale <a> <scalar> -o <out>\n");return 1;}
        const char*out=find_opt(argc,argv,"-o");
        if(!out){fprintf(stderr,"Error: -o required\n");return 1;}
        u32 pa;vector<u32>a;
        if(!read_poly(argv[2],pa,a))return 1;
        MOD=pa;
        u32 c=(u32)(strtoull(argv[3],nullptr,10)%MOD);
        for(auto&x:a)x=(u64)x*c%MOD;
        write_poly(out,pa,a);
        printf("Scaled: %u coefficients\n",(u32)a.size());
        return 0;
    }

    if(cmd=="eval"){
        if(argc<4){fprintf(stderr,"Usage: polytool eval <file> <x>\n");return 1;}
        u32 pa;vector<u32>a;
        if(!read_poly(argv[2],pa,a))return 1;
        MOD=pa;
        u32 x=(u32)(strtoull(argv[3],nullptr,10)%MOD);
        u32 r=0;
        for(int i=(int)a.size()-1;i>=0;i--)r=((u64)r*x+a[i])%MOD;
        printf("%u\n",r);
        return 0;
    }

    fprintf(stderr,"Unknown command '%s'. Run 'polytool help' for usage.\n",cmd.c_str());
    return 1;
}
