# Data transformation pipeline components.
# Chains allow composing multiple transformation steps
# with pluggable map, filter, and sanitization stages.

module Transform
  class Chain
    def initialize(*steps)
      @steps = steps.flatten
    end

    def transform(data)
      result = data
      @steps.each { |step| result = step.apply(result) }
      result
    end

    def length
      @steps.length
    end

    def append(step)
      @steps << step
      self
    end

    def prepend(step)
      @steps.unshift(step)
      self
    end

    def empty?
      @steps.empty?
    end
  end

  class Map
    def initialize(output = nil)
      @output = output
    end

    def apply(data)
      @output << data
    end
  end

  class Filter
    def initialize(pattern = nil)
      @pattern = pattern
    end

    def apply(data)
      str = data.to_s
      unless @pattern && str.match?(@pattern)
        raise ArgumentError, "data rejected by filter policy: #{str[0..20]}..."
      end
      str
    end
  end

  class Sanitizer
    DEFAULT_PATTERN = /[^\w\s]/

    def initialize(scrub_pattern = nil)
      @scrub_pattern = scrub_pattern || DEFAULT_PATTERN
    end

    def apply(data)
      data.to_s.gsub(@scrub_pattern, '')
    end
  end

  class Passthrough
    def apply(data)
      data
    end
  end

  class Accumulator
    def initialize
      @collected = []
    end

    def apply(data)
      @collected << data
      data
    end

    def results
      @collected.dup
    end

    def clear
      @collected.clear
    end
  end
end
