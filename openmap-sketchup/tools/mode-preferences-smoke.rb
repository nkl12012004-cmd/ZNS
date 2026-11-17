# encoding: UTF-8
# Regression for a Full install retaining legacy remote preferences.
require 'json'
require_relative 'bridge-host'
require File.join(File.expand_path(ARGV.fetch(0)), 'main.rb')
core = OpenMapSketchUp::Core

Sketchup.clear_test_preferences
raise 'Fresh install selected remote' unless core.mode == 'bundled'
Sketchup.write_default('OpenMapSketchUp', 'server', 'https://old-server.example')
raise 'Legacy URL selected remote' unless core.mode == 'bundled'
Sketchup.write_default('OpenMapSketchUp', 'mode', 'remote')
raise 'Legacy explicit mode selected remote' unless core.mode == 'bundled'
raise 'Legacy URL was destroyed' unless Sketchup.read_default('OpenMapSketchUp', 'server', nil) == 'https://old-server.example'
Sketchup.write_default('OpenMapSketchUp', 'runtime_mode', 'invalid')
raise 'Invalid mode did not fall back to bundled' unless core.mode == 'bundled'

core.invoke('test-mode', 'set_mode', { 'mode' => 'remote', 'server' => 'https://new-server.example' })
raise 'Explicit remote selection lost' unless core.mode == 'remote' && core.base_url == 'https://new-server.example'
raise 'Remote choice not persisted' unless Sketchup.read_default('OpenMapSketchUp', 'runtime_mode', nil) == 'remote'
core.invoke('test-mode', 'set_mode', { 'mode' => 'bundled' })
raise 'Switch back to local failed' unless core.mode == 'bundled'
raise 'Bundled mode used old URL' unless core.base_url.nil?
core.invoke('test-mode', 'set_mode', { 'mode' => 'remote', 'server' => 'http://untrusted.example' })
raise 'Invalid URL changed the mode' unless core.mode == 'bundled'
puts JSON.generate({ 'mode_preferences' => 'PASS', 'legacy_url' => 'ignored', 'legacy_remote' => 'ignored', 'explicit_remote_persists' => true, 'local_recovery' => true })
