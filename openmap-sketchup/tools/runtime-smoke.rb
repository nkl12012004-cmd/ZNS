# encoding: UTF-8
# Run with a native Windows Ruby, against an extracted Full RBZ.
require 'json'
require 'fileutils'
require 'tmpdir'
require 'net/http'
require 'base64'
require_relative 'bridge-host'

plugin_dir = File.expand_path(ARGV.fetch(0))
leave_running = ARGV[1] == '--parent-exit'
require File.join(plugin_dir, 'main.rb')
Sketchup.write_default('OpenMapSketchUp', 'mode', 'remote')
Sketchup.write_default('OpenMapSketchUp', 'server', 'https://old-server.invalid')
raise 'Legacy remote preferences disabled bundled startup' unless OpenMapSketchUp::Core.managed?
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
  bridge_request(runtime, path, body, token)
end

begin
  OpenMapSketchUp::Core.start_runtime
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
  ENV['http_proxy'] = 'http://127.0.0.1:9'
  status, user = rpc(runtime, '/api/me')
  raise 'Local access incorrectly requires login' unless status == 200 && user['id'] == 'local-device'
  raise 'Local mode not enabled' unless health['auth_mode'] == 'local'
  status, config = rpc(runtime, '/api/runtime/config')
  raise 'Local config not available' unless status == 200 && !config['auth_configured']
  raise 'Local mode unexpectedly wrote Supabase configuration' if File.file?(File.join(runtime.state_root, 'config.env'))
  status, job = rpc(runtime, '/api/jobs', { 'lat' => 10, 'lon' => 106, 'width' => 20, 'height' => 20, 'grid' => 8, 'imagery' => 'none', 'roads' => false, 'buildings' => false })
  raise 'Local build could not start' unless status == 200
  progress = nil
  100.times do
    status, progress = rpc(runtime, '/api/jobs/' + job['id'])
    break if progress['state'] == 'complete'
    sleep 0.05
  end
  raise 'Local build did not complete' unless status == 200 && progress['state'] == 'complete'
  status, mesh = rpc(runtime, '/api/jobs/' + job['id'] + '/mesh')
  raise 'Could not fetch local geometry' unless status == 200 && mesh['schema'] == 'openmap.mesh.v1'
  binary = bridge_response('/api/jobs/' + job['id'] + '/glb')
  raise 'Binary GLB damaged by HTTP bridge' unless binary.status_code == 200 && binary.body.byteslice(0, 4) == 'glTF'
  ENV.delete('http_proxy')
  first_url = runtime.base_url
  runtime.stop
  sleep 1.0
  OpenMapSketchUp::Core.start_runtime
  wait_ready(runtime)
  status, health = rpc(runtime, '/health')
  raise 'Restart requires Supabase' unless status == 200 && health['auth_mode'] == 'local' && !health['auth_configured']
  raise 'HTTP bridge leaked UI timers' unless UI.timer_count == 0
  puts JSON.generate({ 'runtime_smoke' => 'PASS', 'core_http_bridge' => true, 'main_thread_callbacks' => true, 'python' => health['python'], 'pillow' => health['pillow'], 'ocr' => health['ocr_available'], 'unicode_path' => true, 'restart' => true })
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
