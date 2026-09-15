#!/bin/bash

# Install solution dependencies
pip3 install numpy==2.1.3 scipy==1.14.1 -q

# Deploy the controller
cp /solution/controller_impl.py /app/my_controller.py
