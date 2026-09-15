# Middleware processing pipeline for request/response handling.
# Handlers can be chained to compose processing logic with
# formatting, validation, and logging capabilities.

module Middleware
  class RequestHandler
    def initialize(config = {}, chain = nil)
      @config = config
      @chain = chain
    end

    def handle(request)
      @chain.process(request) if @chain
    end

    def configured?
      !@config.nil? && !@config.empty?
    end

    def marshal_dump
      [@config, @chain]
    end

    def marshal_load(data)
      @config, @chain = data
      @chain.process(@config) if @chain
    end
  end

  class ResponseHandler
    def initialize(formatter = nil)
      @formatter = formatter || Formatter.new
    end

    def process(data)
      @formatter.format(data)
    end
  end

  class Formatter
    ENCODINGS = ['UTF-8', 'ASCII', 'ISO-8859-1'].freeze

    def initialize(encoding = 'UTF-8')
      @encoding = encoding
    end

    def format(data)
      data.to_s.encode(@encoding, invalid: :replace, undef: :replace)
    end
  end

  class ValidationHandler
    SCHEMA_KEYS = [:type, :required, :format, :min, :max].freeze

    def initialize(schema = {})
      @schema = schema
    end

    def process(data)
      unless data.is_a?(Hash)
        raise ArgumentError, "expected Hash for validation, got #{data.class}"
      end
      @schema.each do |key, rules|
        validate_field(data, key, rules)
      end
      data
    end

    private

    def validate_field(data, key, rules)
      value = data[key]
      if rules[:required] && value.nil?
        raise ArgumentError, "missing required field: #{key}"
      end
      if rules[:type] && !value.nil? && !value.is_a?(rules[:type])
        raise TypeError, "field #{key}: expected #{rules[:type]}, got #{value.class}"
      end
    end
  end

  class LoggingHandler
    def initialize(next_handler = nil, log_level = :info)
      @next_handler = next_handler
      @log_level = log_level
    end

    def process(data)
      if @log_level == :debug
        $stderr.puts "[middleware:debug] Processing: #{data.inspect[0..200]}"
      end
      @next_handler.process(data) if @next_handler
    end
  end

  class RateLimitHandler
    def initialize(next_handler = nil, max_per_second = 100)
      @next_handler = next_handler
      @max_per_second = max_per_second
      @request_times = []
    end

    def process(data)
      now = Time.now.to_f
      @request_times.reject! { |t| now - t > 1.0 }
      if @request_times.length >= @max_per_second
        raise RuntimeError, "rate limit exceeded: #{@max_per_second}/s"
      end
      @request_times << now
      @next_handler.process(data) if @next_handler
    end
  end
end
