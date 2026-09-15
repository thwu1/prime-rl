#!/usr/bin/env python3
"""SysY language interpreter."""
import sys
from enum import Enum, auto

# ========================== TOKENS ==========================

class TT(Enum):
    INT=auto(); VOID=auto(); CONST=auto(); IF=auto(); ELSE=auto()
    WHILE=auto(); BREAK=auto(); CONTINUE=auto(); RETURN=auto()
    IDENT=auto(); INT_CONST=auto()
    PLUS=auto(); MINUS=auto(); STAR=auto(); SLASH=auto(); PCT=auto()
    LT=auto(); GT=auto(); LE=auto(); GE=auto()
    EQ=auto(); NE=auto(); AND=auto(); OR=auto(); NOT=auto(); ASSIGN=auto()
    LPAREN=auto(); RPAREN=auto(); LBRACK=auto(); RBRACK=auto()
    LBRACE=auto(); RBRACE=auto(); SEMI=auto(); COMMA=auto(); EOF=auto()

KW = {'int':TT.INT,'void':TT.VOID,'const':TT.CONST,'if':TT.IF,'else':TT.ELSE,
      'while':TT.WHILE,'break':TT.BREAK,'continue':TT.CONTINUE,'return':TT.RETURN}

class Tok:
    __slots__=('t','v','ln')
    def __init__(s,t,v,ln): s.t=t; s.v=v; s.ln=ln
    def __repr__(s): return f'{s.t.name}({s.v!r})'

# ========================== LEXER ==========================

class Lexer:
    def __init__(s, src):
        s.src=src; s.p=0; s.ln=1
    def _c(s):
        return s.src[s.p] if s.p<len(s.src) else '\0'
    def _pk(s,n=1):
        i=s.p+n; return s.src[i] if i<len(s.src) else '\0'
    def _adv(s):
        if s.p<len(s.src):
            if s.src[s.p]=='\n': s.ln+=1
            s.p+=1
    def _skip(s):
        while s.p<len(s.src):
            c=s._c()
            if c in ' \t\r\n': s._adv()
            elif c=='/' and s._pk()== '/':
                while s.p<len(s.src) and s._c()!='\n': s._adv()
            elif c=='/' and s._pk()=='*':
                s._adv(); s._adv()
                while s.p+1<len(s.src):
                    if s._c()=='*' and s._pk()=='/':
                        s._adv(); s._adv(); break
                    s._adv()
                else:
                    if s.p<len(s.src): s._adv()
            else: break
    def _num(s,ln):
        st=s.p
        if s._c()=='0' and s._pk() in 'xX':
            s._adv(); s._adv()
            while s._c() in '0123456789abcdefABCDEF': s._adv()
            return Tok(TT.INT_CONST,int(s.src[st:s.p],16),ln)
        elif s._c()=='0' and s._pk() in '01234567':
            while s._c() in '01234567': s._adv()
            return Tok(TT.INT_CONST,int(s.src[st:s.p],8),ln)
        else:
            while s._c().isdigit(): s._adv()
            return Tok(TT.INT_CONST,int(s.src[st:s.p]),ln)
    def tokenize(s):
        ts=[]
        while True:
            s._skip()
            if s.p>=len(s.src): break
            c=s._c(); ln=s.ln
            if c.isalpha() or c=='_':
                st=s.p
                while s._c().isalnum() or s._c()=='_': s._adv()
                w=s.src[st:s.p]; ts.append(Tok(KW.get(w,TT.IDENT),w,ln))
            elif c.isdigit():
                ts.append(s._num(ln))
            elif c=='+': ts.append(Tok(TT.PLUS,'+',ln)); s._adv()
            elif c=='-': ts.append(Tok(TT.MINUS,'-',ln)); s._adv()
            elif c=='*': ts.append(Tok(TT.STAR,'*',ln)); s._adv()
            elif c=='/': ts.append(Tok(TT.SLASH,'/',ln)); s._adv()
            elif c=='%': ts.append(Tok(TT.PCT,'%',ln)); s._adv()
            elif c=='<':
                s._adv()
                if s._c()=='=': s._adv(); ts.append(Tok(TT.LE,'<=',ln))
                else: ts.append(Tok(TT.LT,'<',ln))
            elif c=='>':
                s._adv()
                if s._c()=='=': s._adv(); ts.append(Tok(TT.GE,'>=',ln))
                else: ts.append(Tok(TT.GT,'>',ln))
            elif c=='=':
                s._adv()
                if s._c()=='=': s._adv(); ts.append(Tok(TT.EQ,'==',ln))
                else: ts.append(Tok(TT.ASSIGN,'=',ln))
            elif c=='!':
                s._adv()
                if s._c()=='=': s._adv(); ts.append(Tok(TT.NE,'!=',ln))
                else: ts.append(Tok(TT.NOT,'!',ln))
            elif c=='&':
                s._adv()
                if s._c()=='&': s._adv(); ts.append(Tok(TT.AND,'&&',ln))
                else: raise SyntaxError(f"L{ln}: unexpected '&'")
            elif c=='|':
                s._adv()
                if s._c()=='|': s._adv(); ts.append(Tok(TT.OR,'||',ln))
                else: raise SyntaxError(f"L{ln}: unexpected '|'")
            elif c=='(': ts.append(Tok(TT.LPAREN,'(',ln)); s._adv()
            elif c==')': ts.append(Tok(TT.RPAREN,')',ln)); s._adv()
            elif c=='[': ts.append(Tok(TT.LBRACK,'[',ln)); s._adv()
            elif c==']': ts.append(Tok(TT.RBRACK,']',ln)); s._adv()
            elif c=='{': ts.append(Tok(TT.LBRACE,'{',ln)); s._adv()
            elif c=='}': ts.append(Tok(TT.RBRACE,'}',ln)); s._adv()
            elif c==';': ts.append(Tok(TT.SEMI,';',ln)); s._adv()
            elif c==',': ts.append(Tok(TT.COMMA,',',ln)); s._adv()
            else: raise SyntaxError(f"L{ln}: unexpected '{c}'")
        ts.append(Tok(TT.EOF,None,s.ln))
        return ts

# ========================== PARSER ==========================
# AST uses tuples: (tag, ...)

class Parser:
    def __init__(s, toks):
        s.ts=toks; s.p=0
    def c(s): return s.ts[s.p]
    def pk(s,n=1): return s.ts[min(s.p+n,len(s.ts)-1)]
    def eat(s,tt=None):
        t=s.c()
        if tt and t.t!=tt: raise SyntaxError(f"L{t.ln}: expected {tt}, got {t}")
        s.p+=1; return t
    def match(s,tt):
        if s.c().t==tt: return s.eat()
        return None
    # -- top level --
    def parse(s):
        us=[]
        while s.c().t!=TT.EOF:
            if s.c().t==TT.CONST: us.append(s.p_cdecl())
            elif s.c().t in (TT.INT,TT.VOID):
                if s.c().t==TT.VOID or (s.pk().t==TT.IDENT and s.pk(2).t==TT.LPAREN):
                    us.append(s.p_fdef())
                else: us.append(s.p_vdecl())
            else: raise SyntaxError(f"L{s.c().ln}: unexpected {s.c()}")
        return us
    # -- declarations --
    def p_cdecl(s):
        s.eat(TT.CONST); s.eat(TT.INT)
        ds=[s.p_cdef()]
        while s.match(TT.COMMA): ds.append(s.p_cdef())
        s.eat(TT.SEMI); return ('cdecl',ds)
    def p_cdef(s):
        nm=s.eat(TT.IDENT).v; dims=[]
        while s.c().t==TT.LBRACK:
            s.eat(TT.LBRACK); dims.append(s.p_exp()); s.eat(TT.RBRACK)
        s.eat(TT.ASSIGN); init=s.p_initval()
        return ('cdef',nm,dims,init)
    def p_vdecl(s):
        s.eat(TT.INT); ds=[s.p_vdef()]
        while s.match(TT.COMMA): ds.append(s.p_vdef())
        s.eat(TT.SEMI); return ('vdecl',ds)
    def p_vdef(s):
        nm=s.eat(TT.IDENT).v; dims=[]
        while s.c().t==TT.LBRACK:
            s.eat(TT.LBRACK); dims.append(s.p_exp()); s.eat(TT.RBRACK)
        init=None
        if s.match(TT.ASSIGN): init=s.p_initval()
        return ('vdef',nm,dims,init)
    def p_initval(s):
        if s.c().t==TT.LBRACE:
            s.eat(TT.LBRACE); items=[]
            if s.c().t!=TT.RBRACE:
                items.append(s.p_initval())
                while s.match(TT.COMMA): items.append(s.p_initval())
            s.eat(TT.RBRACE); return ('ilist',items)
        return ('iexp',s.p_exp())
    # -- functions --
    def p_fdef(s):
        rt=s.eat().v; nm=s.eat(TT.IDENT).v
        s.eat(TT.LPAREN); ps=[]
        if s.c().t!=TT.RPAREN:
            ps.append(s.p_fparam())
            while s.match(TT.COMMA): ps.append(s.p_fparam())
        s.eat(TT.RPAREN); body=s.p_block()
        return ('fdef',rt,nm,ps,body)
    def p_fparam(s):
        s.eat(TT.INT); nm=s.eat(TT.IDENT).v; dims=None
        if s.c().t==TT.LBRACK:
            dims=[None]; s.eat(TT.LBRACK); s.eat(TT.RBRACK)
            while s.c().t==TT.LBRACK:
                s.eat(TT.LBRACK); dims.append(s.p_exp()); s.eat(TT.RBRACK)
        return ('par',nm,dims)
    # -- statements --
    def p_block(s):
        s.eat(TT.LBRACE); items=[]
        while s.c().t!=TT.RBRACE: items.append(s.p_bitem())
        s.eat(TT.RBRACE); return ('blk',items)
    def p_bitem(s):
        if s.c().t==TT.CONST: return s.p_cdecl()
        if s.c().t==TT.INT: return s.p_vdecl()
        return s.p_stmt()
    def p_stmt(s):
        t=s.c()
        if t.t==TT.IF: return s.p_if()
        if t.t==TT.WHILE: return s.p_while()
        if t.t==TT.BREAK: s.eat(); s.eat(TT.SEMI); return ('brk',)
        if t.t==TT.CONTINUE: s.eat(); s.eat(TT.SEMI); return ('cont',)
        if t.t==TT.RETURN:
            s.eat(); v=None
            if s.c().t!=TT.SEMI: v=s.p_exp()
            s.eat(TT.SEMI); return ('ret',v)
        if t.t==TT.LBRACE: return s.p_block()
        if t.t==TT.SEMI: s.eat(); return ('empty',)
        e=s.p_exp()
        if s.c().t==TT.ASSIGN:
            s.eat(); val=s.p_exp(); s.eat(TT.SEMI); return ('asgn',e,val)
        s.eat(TT.SEMI); return ('estmt',e)
    def p_if(s):
        s.eat(TT.IF); s.eat(TT.LPAREN); cond=s.p_exp(); s.eat(TT.RPAREN)
        th=s.p_stmt(); el=None
        if s.match(TT.ELSE): el=s.p_stmt()
        return ('if',cond,th,el)
    def p_while(s):
        s.eat(TT.WHILE); s.eat(TT.LPAREN); cond=s.p_exp(); s.eat(TT.RPAREN)
        return ('whl',cond,s.p_stmt())
    # -- expressions --
    def p_exp(s): return s.p_lor()
    def p_lor(s):
        l=s.p_land()
        while s.c().t==TT.OR: s.eat(); l=('bop','||',l,s.p_land())
        return l
    def p_land(s):
        l=s.p_eq()
        while s.c().t==TT.AND: s.eat(); l=('bop','&&',l,s.p_eq())
        return l
    def p_eq(s):
        l=s.p_rel()
        while s.c().t in (TT.EQ,TT.NE):
            op=s.eat().v; l=('bop',op,l,s.p_rel())
        return l
    def p_rel(s):
        l=s.p_add()
        while s.c().t in (TT.LT,TT.GT,TT.LE,TT.GE):
            op=s.eat().v; l=('bop',op,l,s.p_add())
        return l
    def p_add(s):
        l=s.p_mul()
        while s.c().t in (TT.PLUS,TT.MINUS):
            op=s.eat().v; l=('bop',op,l,s.p_mul())
        return l
    def p_mul(s):
        l=s.p_unary()
        while s.c().t in (TT.STAR,TT.SLASH,TT.PCT):
            op=s.eat().v; l=('bop',op,l,s.p_unary())
        return l
    def p_unary(s):
        if s.c().t in (TT.PLUS,TT.MINUS,TT.NOT):
            op=s.eat().v; return ('uop',op,s.p_unary())
        if s.c().t==TT.IDENT and s.pk().t==TT.LPAREN:
            nm=s.eat().v; s.eat(TT.LPAREN); args=[]
            if s.c().t!=TT.RPAREN:
                args.append(s.p_exp())
                while s.match(TT.COMMA): args.append(s.p_exp())
            s.eat(TT.RPAREN); return ('call',nm,args)
        return s.p_primary()
    def p_primary(s):
        if s.c().t==TT.LPAREN:
            s.eat(); e=s.p_exp(); s.eat(TT.RPAREN); return e
        if s.c().t==TT.INT_CONST: return ('num',s.eat().v)
        if s.c().t==TT.IDENT:
            nm=s.eat().v; idxs=[]
            while s.c().t==TT.LBRACK:
                s.eat(); idxs.append(s.p_exp()); s.eat(TT.RBRACK)
            return ('lv',nm,idxs)
        raise SyntaxError(f"L{s.c().ln}: unexpected {s.c()} in expr")

# ======================== INTERPRETER ========================

class RetSig(Exception):
    def __init__(s,v=None): s.v=v
class BrkSig(Exception): pass
class ContSig(Exception): pass

class Env:
    def __init__(s, par=None):
        s.par=par; s.vs={}; s.cst=set()
    def define(s, nm, val, const=False):
        s.vs[nm]=val
        if const: s.cst.add(nm)
    def get(s, nm):
        if nm in s.vs: return s.vs[nm]
        if s.par: return s.par.get(nm)
        raise RuntimeError(f"Undefined: {nm}")
    def set(s, nm, val):
        if nm in s.vs: s.vs[nm]=val; return
        if s.par: s.par.set(nm,val); return
        raise RuntimeError(f"Undefined: {nm}")

class Interp:
    def __init__(s, prog):
        s.prog=prog; s.genv=Env(); s.fns={}
        s.inbuf=''; s.inpos=0

    def run(s):
        for nm in ('getint','getch','getarray','putint','putch','putarray'):
            s.fns[nm]=('builtin',nm)
        try:
            if not sys.stdin.isatty():
                s.inbuf=sys.stdin.read()
            else:
                s.inbuf=''
        except Exception:
            s.inbuf=''
        s.inpos=0
        for u in s.prog:
            tag=u[0]
            if tag=='fdef': s.fns[u[2]]=u
            elif tag=='vdecl': s._xvdecl(u, s.genv, gl=True)
            elif tag=='cdecl': s._xcdecl(u, s.genv)
        ret=s._call('main',[])
        sys.stdout.flush()
        return ret if ret is not None else 0

    # -- function calls --
    def _call(s, nm, args):
        fn=s.fns.get(nm)
        if fn is None: raise RuntimeError(f"Undefined fn: {nm}")
        if fn[0]=='builtin': return s._builtin(fn[1],args)
        _,rt,_,params,body=fn
        env=Env(s.genv)
        for par,arg in zip(params,args):
            env.define(par[1],arg)
        try:
            s._xblk(body,env)
            return 0
        except RetSig as e:
            return e.v if e.v is not None else 0

    def _builtin(s,nm,args):
        if nm=='putint': sys.stdout.write(str(args[0])); return None
        if nm=='putch': sys.stdout.write(chr(args[0])); return None
        if nm=='putarray':
            n,arr=args[0],args[1]
            sys.stdout.write(f"{n}:")
            for i in range(n): sys.stdout.write(f" {arr[i]}")
            sys.stdout.write("\n"); return None
        if nm=='getint': return s._rint()
        if nm=='getch': return s._rch()
        if nm=='getarray':
            arr=args[0]; n=s._rint()
            for i in range(n): arr[i]=s._rint()
            return n
        return None

    def _rint(s):
        while s.inpos<len(s.inbuf) and s.inbuf[s.inpos] in ' \t\n\r':
            s.inpos+=1
        st=s.inpos
        if s.inpos<len(s.inbuf) and s.inbuf[s.inpos] in '+-': s.inpos+=1
        while s.inpos<len(s.inbuf) and s.inbuf[s.inpos].isdigit(): s.inpos+=1
        return int(s.inbuf[st:s.inpos]) if s.inpos>st else 0

    def _rch(s):
        if s.inpos<len(s.inbuf):
            c=s.inbuf[s.inpos]; s.inpos+=1; return ord(c)
        return -1

    # -- declarations --
    def _xvdecl(s, node, env, gl=False):
        for d in node[1]:
            _,nm,dims,init=d
            if dims:
                dsz=[s._ev(dm,env) for dm in dims]
                arr=s._mkarr(dsz)
                if init: s._fillarr(arr,dsz,init,env)
                env.define(nm,arr)
            else:
                v=0
                if init:
                    if init[0]=='iexp': v=s._ev(init[1],env)
                env.define(nm,v)

    def _xcdecl(s, node, env):
        for d in node[1]:
            _,nm,dims,init=d
            if dims:
                dsz=[s._ev(dm,env) for dm in dims]
                arr=s._mkarr(dsz)
                if init: s._fillarr(arr,dsz,init,env)
                env.define(nm,arr,const=True)
            else:
                v=s._ev(init[1],env)
                env.define(nm,v,const=True)

    def _mkarr(s,dims):
        if len(dims)==1: return [0]*dims[0]
        return [s._mkarr(dims[1:]) for _ in range(dims[0])]

    def _fillarr(s,arr,dims,init,env):
        if init[0]!='ilist': return
        s._fill(arr,dims,init[1],env)

    def _fill(s,arr,dims,items,env):
        if len(dims)==1:
            for i in range(min(dims[0],len(items))):
                it=items[i]
                if it[0]=='iexp': arr[i]=s._ev(it[1],env)
            return
        sub=dims[1:]
        ssz=1
        for d in sub: ssz*=d
        i=0
        for j in range(dims[0]):
            if i>=len(items): break
            it=items[i]
            if it[0]=='ilist':
                s._fill(arr[j],sub,it[1],env); i+=1
            else:
                flat=items[i:i+ssz]
                s._fill(arr[j],sub,flat,env); i+=len(flat)

    # -- statement execution --
    def _xblk(s,node,penv):
        for it in node[1]: s._xitem(it,penv)

    def _xitem(s,node,env):
        tag=node[0]
        if tag=='vdecl': s._xvdecl(node,env)
        elif tag=='cdecl': s._xcdecl(node,env)
        else: s._xstmt(node,env)

    def _xstmt(s,node,env):
        tag=node[0]
        if tag=='asgn':
            val=s._ev(node[2],env)
            s._asgn(node[1],val,env)
        elif tag=='estmt':
            s._ev(node[1],env)
        elif tag=='blk':
            s._xblk(node,env)
        elif tag=='if':
            _,cond,th,el=node
            if s._ev(cond,env)!=0: s._xstmt(th,env)
            elif el: s._xstmt(el,env)
        elif tag=='whl':
            _,cond,body=node
            while s._ev(cond,env)!=0:
                try: s._xstmt(body,env)
                except BrkSig: break
                except ContSig: continue
        elif tag=='brk': raise BrkSig()
        elif tag=='cont': raise ContSig()
        elif tag=='ret':
            v=s._ev(node[1],env) if node[1] else None
            raise RetSig(v)
        elif tag=='empty': pass

    def _asgn(s,lv,val,env):
        _,nm,idxs=lv
        if not idxs:
            env.set(nm,val)
        else:
            obj=env.get(nm)
            for ix in idxs[:-1]:
                obj=obj[s._ev(ix,env)]
            obj[s._ev(idxs[-1],env)]=val

    # -- expression evaluation --
    def _ev(s,node,env):
        tag=node[0]
        if tag=='num': return node[1]
        if tag=='lv':
            _,nm,idxs=node
            obj=env.get(nm)
            for ix in idxs:
                obj=obj[s._ev(ix,env)]
            return obj
        if tag=='bop':
            _,op,l,r=node
            if op=='&&':
                lv=s._ev(l,env); rv=s._ev(r,env)
                return 1 if (lv!=0 and rv!=0) else 0
            if op=='||':
                lv=s._ev(l,env)
                return 1 if lv!=0 else (1 if s._ev(r,env)!=0 else 0)
            lv=s._ev(l,env); rv=s._ev(r,env)
            if op=='+': return lv+rv
            if op=='-': return lv-rv
            if op=='*': return lv*rv
            if op=='/': return lv//rv if rv else 0
            if op=='%': return lv%rv if rv else 0
            if op=='<': return 1 if lv<rv else 0
            if op=='>': return 1 if lv>rv else 0
            if op=='<=': return 1 if lv<=rv else 0
            if op=='>=': return 1 if lv>=rv else 0
            if op=='==': return 1 if lv==rv else 0
            if op=='!=': return 1 if lv!=rv else 0
        if tag=='uop':
            _,op,operand=node; v=s._ev(operand,env)
            if op=='+': return v
            if op=='-': return -v
            if op=='!': return 1 if v==0 else 0
        if tag=='call':
            _,nm,aexps=node; args=[]
            for a in aexps:
                if a[0]=='lv':
                    obj=env.get(a[1])
                    for ix in a[2]:
                        obj=obj[s._ev(ix,env)]
                    args.append(list(obj) if isinstance(obj,list) else obj)
                else:
                    args.append(s._ev(a,env))
            return s._call(nm,args)
        raise RuntimeError(f"Unknown node: {tag}")

# =========================== MAIN ===========================

def main():
    if len(sys.argv)<2:
        print("Usage: sysy_interp <source.sy>",file=sys.stderr); sys.exit(1)
    with open(sys.argv[1]) as f:
        src=f.read()
    toks=Lexer(src).tokenize()
    prog=Parser(toks).parse()
    ret=Interp(prog).run()
    sys.exit(ret%256)

if __name__=='__main__':
    main()
