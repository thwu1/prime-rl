# Stream writer abstractions for directing output to
# various targets. Writers implement << or write for
# composability with transformation pipelines.

module Stream
  class DirectWriter
    def initialize(target = nil)
      @target = target
    end

    def <<(data)
      @target.call(data.to_s)
    end

    def close
      @target = nil
    end
  end

  class BufferedWriter
    def initialize(target = nil, threshold = 1024)
      @target = target
      @threshold = threshold
      @buf = ''
    end

    def <<(data)
      @buf = (@buf || '') + data.to_s
      if @buf.length >= (@threshold || 1024)
        @target.call(@buf)
        @buf = ''
      end
      self
    end

    def flush
      unless (@buf || '').empty?
        @target.call(@buf)
        @buf = ''
      end
    end

    def pending_bytes
      (@buf || '').length
    end
  end

  class NullWriter
    def <<(data)
      self
    end

    def write(data)
      self
    end

    def flush; end
  end

  class SafeWriter
    STRIP_PATTERN = /[^a-zA-Z0-9\s]/

    def write(data)
      sanitized = data.to_s.gsub(STRIP_PATTERN, '')
      @delegate.call(sanitized) if @delegate
    end
  end

  class TypedWriter
    def write(data)
      raise TypeError, "expected String, got #{data.class}" unless data.is_a?(String)
      @output << data
    end
  end

  class AsyncWriter
    def initialize(queue = nil)
      @queue = queue
      @dropped = 0
    end

    def <<(data)
      if @queue
        @queue.push(data.to_s)
      else
        @dropped += 1
      end
      self
    end

    def dropped_count
      @dropped
    end
  end

  class TeeWriter
    def initialize(*targets)
      @targets = targets
    end

    def <<(data)
      @targets.each { |t| t << data }
      self
    end

    def write(data)
      @targets.each { |t| t.write(data) }
      self
    end
  end
end
