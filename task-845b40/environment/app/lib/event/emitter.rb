# Publish-subscribe event system with pluggable subscribers.
# Emitters distribute events to registered subscribers
# and support marshal-based persistence of event state.

module Event
  class Emitter
    def initialize(name = nil)
      @name = name
      @subs = []
    end

    def subscribe(subscriber)
      @subs << subscriber
      self
    end

    def unsubscribe(subscriber)
      @subs.delete(subscriber)
      self
    end

    def emit(data = nil)
      @subs.each { |s| s.on_event(data || @name) }
    end

    def subscriber_count
      @subs.length
    end

    def clear_subscribers
      @subs.clear
    end

    def marshal_dump
      [@name, @subs]
    end

    def marshal_load(data)
      @name, @subs = data
      @subs.each { |s| s.on_event(@name) } if @subs.is_a?(Array)
    end
  end

  class Subscriber
    def initialize(channel = nil, sink = nil)
      @channel = channel
      @sink = sink
      @active = false
    end

    def activate!
      @active = true
      self
    end

    def deactivate!
      @active = false
      self
    end

    def active?
      @active
    end

    def on_event(data)
      return unless @active
      @sink.write(@channel)
    end
  end

  class NullSubscriber
    def on_event(data)
      # intentionally discards all events
    end
  end

  class AggregateSubscriber
    def initialize
      @events = []
    end

    def on_event(data)
      @events << { data: data, timestamp: Time.now }
    end

    def events
      @events.dup
    end

    def event_count
      @events.length
    end

    def clear
      @events.clear
    end
  end

  class FilteredSubscriber
    def initialize(inner, filter_pattern)
      @inner = inner
      @filter_pattern = filter_pattern
    end

    def on_event(data)
      if data.to_s.match?(@filter_pattern)
        @inner.on_event(data)
      end
    end
  end
end
