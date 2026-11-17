# encoding: UTF-8
# Run with a native Windows Ruby, against an extracted Full RBZ.
require 'json'
require 'fileutils'
require 'tmpdir'
require 'net/http'
require 'base64'
module Sketchup
  class AppObserver; end
end

plugin_dir = File.expand_path(ARGV.fetch(0))
leave_running = ARGV[1] == '--parent-exit'
require File.join(plugin_dir, 'runtime.rb')
runtime = OpenMapSketchUp::Runtime
raise 'Windows x64 runner required' unless runtime.supported?

temp = Dir.mktmpdir('OpenMap kiểm thử ')
ENV['OPENMAP_STATE_DIR'] = File.join(temp, 'hồ sơ người dùng')

def wait_ready(runtime)
  deadline = Process.clock_gettime(Process::CLOCK_MONOTONIC) + 150
  loop do
    state = runtime.status
    raise state['message'] if state['state'] == 'error'
    return if state['state'] == 'ready'
    raise 'Worker startup timeout' if Process.clock_gettime(Process::CLOCK_MONOTONIC) > deadline
    sleep 0.1
  end
end

def rpc(runtime, path, body = nil, token = nil)
  uri = URI(runtime.base_url + path)
  request = body ? Net::HTTP::Post.new(uri) : Net::HTTP::Get.new(uri)
  request['X-OpenMap-Local'] = runtime.transport_token
  request['Authorization'] = 'Bearer ' + token if token
  request['Content-Type'] = 'application/json'
  request.body = JSON.generate(body) if body
  response = Net::HTTP.start(uri.host, uri.port, nil, nil, nil, nil, read_timeout: 15) { |http| http.request(request) }
  [response.code.to_i, JSON.parse(response.body)]
end

begin
  runtime.start(File.join(plugin_dir, 'server'))
  wait_ready(runtime)
  if leave_running
    File.write(ENV.fetch('OPENMAP_PARENT_PROBE'), JSON.generate({ 'url' => runtime.base_url, 'token' => runtime.transport_token, 'state_root' => runtime.state_root }))
    puts 'Parent-exit probe ready'
    exit
  end
  status, health = rpc(runtime, '/health')
  raise 'Health not ready' unless status == 200 && health['ocr_available'] && health['python'].start_with?('3.14.')
  uri = URI(runtime.base_url + '/health')
  rejected = Net::HTTP.start(uri.host, uri.port, nil, nil, nil, nil) { |http| http.get(uri.request_uri) }
  raise 'Transport nonce bypassed' unless rejected.code == '403'
  status, _data = rpc(runtime, '/api/me')
  raise 'Anonymous login bypassed' unless status == 401
  status, config = rpc(runtime, '/api/runtime/config')
  raise 'Local config not available' unless status == 200 && !config['auth_configured']
  status, _data = rpc(runtime, '/api/runtime/config', { 'supabase_url' => 'https://example.supabase.co', 'public_key' => 'test-public-key' })
  raise 'Could not persist config' unless status == 200 && File.file?(File.join(runtime.state_root, 'config.env'))
  first_url = runtime.base_url
  runtime.stop
  sleep 1.0
  runtime.start(File.join(plugin_dir, 'server'))
  wait_ready(runtime)
  status, health = rpc(runtime, '/health')
  raise 'Restart did not restore config' unless status == 200 && health['auth_configured']
  puts JSON.generate({ 'runtime_smoke' => 'PASS', 'python' => health['python'], 'pillow' => health['pillow'], 'ocr' => health['ocr_available'], 'unicode_path' => true, 'restart' => true })
rescue StandardError
  Dir.glob(File.join(runtime.state_root, 'worker-*.log')).each { |path| warn(File.read(path, encoding: 'UTF-8')) }
  raise
ensure
  unless leave_running
    runtime.stop
    sleep 1.0
    FileUtils.rm_rf(temp)
  end
end
