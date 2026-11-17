# encoding: UTF-8
# Minimal host for exercising the actual Core HTTP bridge outside SketchUp.
# It deliberately rejects Sketchup::Http so managed calls cannot silently use it.
module Sketchup
  class AppObserver; end
  class ModelObserver; end
  @test_preferences = {}
  def self.read_default(section, key, default)
    @test_preferences.fetch([section, key], default)
  end
  def self.write_default(section, key, value)
    @test_preferences[[section, key]] = value
  end
  def self.clear_test_preferences
    @test_preferences.clear
  end
  def self.find_support_file(_name)
    nil
  end
  module Http
    GET, POST, DELETE = 0, 1, 2
    class Request
      def self.new(*_args)
        raise 'Managed API incorrectly called Sketchup::Http'
      end
    end
  end
end

module UI
  @timers, @sequence = {}, 0
  def self.start_timer(_interval, _repeat, &block)
    raise 'UI timer called from worker thread' unless Thread.current == Thread.main
    @sequence += 1
    @timers[@sequence] = block
    @sequence
  end
  def self.stop_timer(id)
    raise 'UI timer stopped from worker thread' unless Thread.current == Thread.main
    @timers.delete(id)
  end
  def self.pump
    @timers.dup.each_value(&:call)
  end
  def self.timer_count
    @timers.length
  end
end

def file_loaded?(_path)
  true
end
$LOADED_FEATURES << 'sketchup.rb'

def bridge_response(path, body = nil, token = nil)
  core = OpenMapSketchUp::Core
  core.instance_variable_set(:@token, token)
  result = nil
  core.http(body ? 'POST' : 'GET', path, body) do |response, failure|
    raise 'Bridge callback ran outside main thread' unless Thread.current == Thread.main
    result = [response, failure]
  end
  deadline = Process.clock_gettime(Process::CLOCK_MONOTONIC) + 150
  until result
    raise 'HTTP bridge callback timeout' if Process.clock_gettime(Process::CLOCK_MONOTONIC) > deadline
    UI.pump
    sleep 0.01
  end
  response, failure = result
  raise failure if failure
  response
end

def bridge_request(_runtime, path, body = nil, token = nil)
  response = bridge_response(path, body, token)
  [response.status_code, JSON.parse(response.body)]
end
