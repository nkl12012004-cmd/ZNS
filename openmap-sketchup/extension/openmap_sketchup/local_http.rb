# encoding: UTF-8
# SPDX-License-Identifier: MIT
require 'net/http'
require 'uri'
require 'thread'

module OpenMapSketchUp
  module LocalHTTP
    MAX_RESPONSE = 140_000_000
    Response = Struct.new(:status_code, :body)

    # The managed worker always binds IPv4 loopback. Explicitly disable proxy
    # discovery: a system proxy must never receive the local IPC/session headers.
    def self.request(url, method, headers, body)
      uri = URI.parse(url)
      unless uri.scheme == 'http' && uri.host == '127.0.0.1' && !uri.userinfo && !uri.fragment
        raise 'Địa chỉ bộ xử lý cục bộ không hợp lệ.'
      end
      type = { 'GET' => Net::HTTP::Get, 'POST' => Net::HTTP::Post, 'DELETE' => Net::HTTP::Delete }[method]
      raise 'Phương thức HTTP không hợp lệ.' unless type
      request = type.new(uri.request_uri, headers)
      request.body = body if body
      http = Net::HTTP.new(uri.host, uri.port, nil)
      http.open_timeout = 5
      http.read_timeout = 120
      http.write_timeout = 30 if http.respond_to?(:write_timeout=)
      http.max_retries = 0 if http.respond_to?(:max_retries=)
      http.start do |connection|
        connection.request(request) do |response|
          if response.content_length && response.content_length > MAX_RESPONSE
            raise 'Phản hồi quá lớn. Chia vùng thành mảnh nhỏ hơn.'
          end
          bytes = ''.b
          response.read_body do |chunk|
            raise 'Phản hồi quá lớn. Chia vùng thành mảnh nhỏ hơn.' if bytes.bytesize + chunk.bytesize > MAX_RESPONSE
            bytes << chunk
          end
          return Response.new(response.code.to_i, bytes)
        end
      end
    end

    # Only the network runs in a Ruby thread. All callbacks that touch SketchUp
    # or HtmlDialog are delivered by its UI timer on the main thread.
    def self.start(url, method, headers, body, &callback)
      completed = Queue.new
      timer = UI.start_timer(0.05, true) do
        unless completed.empty?
          response, failure = completed.pop
          UI.stop_timer(timer)
          callback.call(response, failure)
        end
      end
      Thread.new do
        begin
          completed << [request(url, method, headers, body), nil]
        rescue StandardError => error
          message = if error.is_a?(IOError) || error.is_a?(SystemCallError) || error.is_a?(Timeout::Error) || error.is_a?(Net::HTTPBadResponse)
                      'Không nhận được phản hồi hợp lệ từ bộ xử lý cục bộ. Mở Cấu hình → Khởi động lại; nếu vẫn lỗi, mở nhật ký worker.'
                    else
                      error.message
                    end
          completed << [nil, message]
        end
      end
    end
  end
end
