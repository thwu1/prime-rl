#!/bin/bash

pip3 install packaging==24.2 -q

mkdir -p /app/resolver

cp /solution/resolver_impl.py /app/resolver/__init__.py
