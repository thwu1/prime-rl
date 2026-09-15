FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip g++ && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app && python3 -c "import random; random.seed(42); n,k,m=5000,500,10000; a=[random.randint(501,9500) for _ in range(n)]; f=open('/app/input.txt','w'); f.write('%d %d %d\n'%(n,m,k)); f.write(' '.join(map(str,a))+'\n'); f.close()"

WORKDIR /app
