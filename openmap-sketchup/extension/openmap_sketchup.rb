# encoding: UTF-8
# SPDX-License-Identifier: MIT
require 'sketchup.rb'
require 'extensions.rb'

module OpenMapSketchUp
  VERSION = '0.2.0'.freeze unless const_defined?(:VERSION)
  unless file_loaded?(__FILE__)
    extension = SketchupExtension.new('OpenMap SketchUp', 'openmap_sketchup/main')
    extension.version = VERSION
    extension.creator = 'OpenMap contributors'
    extension.description = 'Bản đồ, DEM và OSM; đăng nhập Supabase Email/Google. Mã nguồn MIT.'
    extension.copyright = '2026 OpenMap contributors'
    Sketchup.register_extension(extension, true)
    file_loaded(__FILE__)
  end
end
