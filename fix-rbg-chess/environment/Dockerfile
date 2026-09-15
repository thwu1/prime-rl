FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y g++ make git libboost-all-dev python3-pip && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN git clone https://github.com/marekesz/rbg.git /app/rbg

# Remove all draughts/checkers game descriptions to prevent the agent
# from finding a correct reference implementation
RUN find /app/rbg/rbgGames -iname '*draughts*' -delete && \
    find /app/rbg/rbgGames -iname '*checkers*' -delete && \
    find /app/rbg/rbgGames -iname '*checker*' -delete && \
    find /app/rbg/rbgGameSpecificReasoners -iname '*draughts*' -delete 2>/dev/null; true && \
    find /app/rbg/rbgGameSpecificReasoners -iname '*checkers*' -delete 2>/dev/null; true

# Build the RBG parser library
RUN cd /app/rbg/rbgParser && make rbgParser

# Build the RBG-to-C++ compiler
RUN cd /app/rbg/rbg2cpp && make rbg2cpp

# Remove git history to prevent recovering deleted game files from version control
RUN rm -rf /app/rbg/.git
