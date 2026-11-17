# encoding: UTF-8
# SPDX-License-Identifier: MIT
require 'sketchup.rb'
require 'extensions.rb'

module OpenMapSketchUp
  VERSION = '0.4.1'.freeze unless const_defined?(:VERSION)
  unless file_loaded?(__FILE__)
    extension = SketchupExtension.new('SiteCraft', 'openmap_sketchup/main')
    extension.version = VERSION
    extension.creator = 'SiteCraft contributors'
    extension.description = 'Bản đồ, DEM và OSM; mở trực tiếp, không cần tài khoản. Mã nguồn chỉnh sửa được; xem NOTICE về quyền của các thành phần.'
    extension.copyright = '2026 SiteCraft contributors'
    Sketchup.register_extension(extension, true)
    file_loaded(__FILE__)
  end
end
