# encoding: UTF-8
# SPDX-License-Identifier: MIT
require 'sketchup.rb'
require 'extensions.rb'

module OpenMapSketchUp
  VERSION = '0.5.0-beta.1'.freeze unless const_defined?(:VERSION)
  unless file_loaded?(__FILE__)
    extension = SketchupExtension.new('SiteCraft', 'openmap_sketchup/main')
    extension.version = VERSION
    extension.creator = 'SiteCraft contributors'
    extension.description = 'Bản đồ, DEM, OSM và Render AI qua Chrome/Google Flow. Bản đồ mở trực tiếp; Flow dùng tài khoản/hạn mức Google riêng. Xem NOTICE về quyền các thành phần.'
    extension.copyright = '2026 SiteCraft contributors'
    Sketchup.register_extension(extension, true)
    file_loaded(__FILE__)
  end
end
