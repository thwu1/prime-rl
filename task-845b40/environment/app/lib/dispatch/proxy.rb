# Method dispatch proxies for deferred and controlled
# invocation patterns. Proxies wrap receiver + method
# pairs with various safety and logging policies.

module Dispatch
  class MethodProxy
    def initialize(receiver = nil, method_name = nil)
      @receiver = receiver
      @method_name = method_name
    end

    def call(input)
      @receiver.send(@method_name, input)
    end

    def to_s
      "#<MethodProxy #{@receiver}.#{@method_name}>"
    end

    def bound?
      !@receiver.nil? && !@method_name.nil?
    end
  end

  class SafeProxy
    ALLOWED = [
      :to_s, :inspect, :freeze, :dup, :hash,
      :length, :size, :empty?, :nil?, :class,
      :is_a?, :respond_to?, :object_id
    ].freeze

    def initialize(receiver = nil, method_name = nil)
      @receiver = receiver
      @method_name = method_name
    end

    def call(input = nil)
      unless ALLOWED.include?(@method_name)
        raise SecurityError, "method '#{@method_name}' is not in the dispatch allowlist"
      end
      @receiver.send(@method_name)
    end

    def allowed_methods
      ALLOWED
    end
  end

  class LoggedProxy
    def initialize(receiver = nil, method_name = nil, log_path = '/var/log/dispatch.log')
      @receiver = receiver
      @method_name = method_name
      @log_path = log_path
    end

    def call(input)
      File.open(@log_path, 'a') do |f|
        f.puts "[#{Time.now.iso8601}] dispatch #{@method_name}(#{input.inspect[0..100]})"
      end
      raise SecurityError, "dispatched calls are audit-only in this environment"
    end

    def log_path
      @log_path
    end
  end

  class BatchProxy
    def initialize(proxies = [])
      @proxies = proxies
    end

    def call(input)
      results = []
      @proxies.each { |p| results << p.call(input) }
      results
    end

    def size
      @proxies.length
    end
  end

  class ConditionalProxy
    def initialize(proxy = nil, condition = nil)
      @proxy = proxy
      @condition = condition
    end

    def call(input)
      if @condition && @condition.call(input)
        @proxy.call(input)
      end
    end
  end
end
