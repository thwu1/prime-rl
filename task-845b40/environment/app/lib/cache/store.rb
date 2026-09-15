# Pluggable cache storage with configurable serialization.
# Supports multiple backends and serializer strategies for
# transparent object caching across process boundaries.

module Cache
  class Store
    attr_reader :name

    def initialize(name, backend, serializer)
      @name = name
      @backend = backend
      @serializer = serializer
    end

    def get(key)
      raw = @backend.fetch(key)
      return nil if raw.nil?
      @serializer.hydrate(raw)
    end

    def set(key, value, ttl: nil)
      raw = @serializer.dehydrate(value)
      @backend.store(key, raw, ttl: ttl)
    end

    def delete(key)
      @backend.remove(key)
    end

    def clear
      @backend.flush
    end

    def stats
      {
        name: @name,
        size: @backend.respond_to?(:size) ? @backend.size : -1,
        serializer: @serializer.class.name
      }
    end

    def marshal_dump
      [@backend, @serializer]
    end

    def marshal_load(data)
      @backend, @serializer = data
      @serializer.hydrate(@backend)
    end
  end

  class NullStore
    def get(key); nil; end
    def set(key, value, ttl: nil); nil; end
    def delete(key); nil; end
    def clear; nil; end

    def stats
      { name: 'null', size: 0 }
    end

    def marshal_dump
      nil
    end

    def marshal_load(data)
      # Intentionally empty - null store preserves no state
    end
  end

  class MemoryBackend
    def initialize
      @data = {}
      @access_log = []
    end

    def fetch(key)
      @access_log << [:fetch, key, Time.now]
      @data[key]
    end

    def store(key, value, ttl: nil)
      @access_log << [:store, key, Time.now]
      @data[key] = value
    end

    def remove(key)
      @data.delete(key)
    end

    def flush
      @data.clear
      @access_log.clear
    end

    def size
      @data.length
    end

    def recent_accesses(n = 10)
      @access_log.last(n)
    end
  end
end
