#!/usr/bin/env ruby
require 'base64'

$LOAD_PATH.unshift(File.join(__dir__, 'lib'))

require 'cache/store'
require 'cache/serializer'
require 'transform/chain'
require 'stream/writer'
require 'dispatch/proxy'
require 'event/emitter'
require 'middleware/handler'

if ARGV.empty?
  $stderr.puts "Usage: ruby deserialize.rb <base64_payload>"
  exit 1
end

payload = ARGV[0]
decoded = Base64.decode64(payload)
result = Marshal.load(decoded)
puts "Deserialized: #{result.inspect}"
