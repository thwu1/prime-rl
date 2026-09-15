require 'json'

# Serializer strategies for cache hydration/dehydration.
# Each serializer converts between stored representations
# and runtime objects.

module Cache
  class JsonSerializer
    def hydrate(data)
      return {} if data.nil?
      JSON.parse(data.to_s)
    rescue JSON::ParserError
      {}
    end

    def dehydrate(obj)
      JSON.generate(obj)
    end

    def content_type
      'application/json'
    end
  end

  class ObjectSerializer
    def initialize(transformer = nil)
      @transformer = transformer
    end

    def hydrate(data)
      @transformer.transform(data)
    end

    def dehydrate(obj)
      obj.to_s
    end

    def content_type
      'application/octet-stream'
    end
  end

  class YamlSerializer
    def hydrate(data)
      require 'yaml'
      YAML.safe_load(data.to_s, permitted_classes: [Symbol, Date, Time])
    rescue Psych::SyntaxError
      nil
    end

    def dehydrate(obj)
      require 'yaml'
      YAML.dump(obj)
    end

    def content_type
      'application/x-yaml'
    end
  end

  class CompressedSerializer
    def initialize(inner)
      @inner = inner
    end

    def hydrate(data)
      require 'zlib'
      decompressed = Zlib::Inflate.inflate(data)
      @inner.hydrate(decompressed)
    rescue Zlib::Error
      @inner.hydrate(data)
    end

    def dehydrate(obj)
      require 'zlib'
      raw = @inner.dehydrate(obj)
      Zlib::Deflate.deflate(raw)
    end

    def content_type
      @inner.content_type
    end
  end
end
