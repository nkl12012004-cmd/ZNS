# ==============================================================================
# File: mapskp/runtime_bootstrap.rb
# MapSKP v2.8.1 — Khởi Tạo Độc Lập, Xác Thực IPC v2 Per-Request & Giao Dịch Cập Nhật Ed25519
# ==============================================================================

require 'sketchup.rb'
require 'fileutils'
require 'socket'
require 'tmpdir'
require 'zlib'
require 'json'
require 'digest'
require 'securerandom'
require 'base64'

begin
  require 'openssl'
rescue LoadError
  nil
end

begin
  require 'fiddle'
rescue LoadError
  nil
end

module MapSKP
  module Bootstrap
    PORT_RANGE                      = (8807..8825).to_a.freeze unless const_defined?(:PORT_RANGE)
    ENGINE_VERSION_TAG              = "v2.8.1".freeze unless const_defined?(:ENGINE_VERSION_TAG)
    READY_MARKER_NAME               = ".pak_v281_ready".freeze unless const_defined?(:READY_MARKER_NAME)
    PAK_MAGIC                       = "MAPSKPRT1".freeze unless const_defined?(:PAK_MAGIC)
    PINNED_PUBLISHER_ED25519_PUB_HEX = "f63a160cce334dcc58a86d3d094163a397e6461e65061b8fe3f506aefac9d85a".freeze unless const_defined?(:PINNED_PUBLISHER_ED25519_PUB_HEX)
    EXPECTED_ABI_PYD_NAME           = "mapskp_armor.cp314-win_amd64.pyd".freeze unless const_defined?(:EXPECTED_ABI_PYD_NAME)
    EXPECTED_ABI_TAG                = "cp314-win_amd64".freeze unless const_defined?(:EXPECTED_ABI_TAG)
    CURRENT_BUILD_NUMBER            = 20801 unless const_defined?(:CURRENT_BUILD_NUMBER)

    MAX_PAK_ENTRIES           = 2_500 unless const_defined?(:MAX_PAK_ENTRIES)
    MAX_PAK_SINGLE_BYTES      = 64 * 1024 * 1024 unless const_defined?(:MAX_PAK_SINGLE_BYTES)
    MAX_PAK_TOTAL_BYTES       = 240 * 1024 * 1024 unless const_defined?(:MAX_PAK_TOTAL_BYTES)
    MAX_PAK_PATH_LEN          = 240 unless const_defined?(:MAX_PAK_PATH_LEN)
    MAX_JOURNAL_BYTES         = 262_144 unless const_defined?(:MAX_JOURNAL_BYTES)
    MAX_HOTPATCH_ZIP_BYTES    = 16 * 1024 * 1024 unless const_defined?(:MAX_HOTPATCH_ZIP_BYTES)
    MAX_HOTPATCH_SINGLE_BYTES = 16 * 1024 * 1024 unless const_defined?(:MAX_HOTPATCH_SINGLE_BYTES)
    MAX_HOTPATCH_TOTAL_BYTES  = 48 * 1024 * 1024 unless const_defined?(:MAX_HOTPATCH_TOTAL_BYTES)

    unless const_defined?(:WIN_RESERVED_NAMES)
      WIN_RESERVED_NAMES = %w[
        CON PRN AUX NUL
        COM1 COM2 COM3 COM4 COM5 COM6 COM7 COM8 COM9
        LPT1 LPT2 LPT3 LPT4 LPT5 LPT6 LPT7 LPT8 LPT9
      ].freeze
    end

    @active_port ||= 8807
    @runtime_source ||= "uninitialized"
    @spawned_by_self ||= false
    @spawned_pid ||= 0
    @ipc_token ||= ""
    @win_get_file_attrs ||= nil
    @win_find_first_file ||= nil
    @win_find_close ||= nil
    @win_crypt_protect ||= nil
    @win_crypt_unprotect ||= nil
    @win_local_free ||= nil
    @in_active_update_tx_id ||= nil

    def self.active_port
      @active_port
    end

    def self.runtime_source
      @runtime_source
    end

    def self.ipc_token
      @ipc_token
    end

    def self.spawned_pid
      @spawned_pid
    end

    def self.app_state_root
      local_app = ENV["LOCALAPPDATA"].to_s.tr("\\", "/")
      base = local_app.empty? ? Dir.tmpdir.tr("\\", "/") : local_app
      File.join(base, "HiepAI_Studio", "MapSKP")
    end

    # W11.8 (MIG-01): Xóa bỏ tệp marker IPC cũ từ phiên bản trước để không bao giờ tái sử dụng token trên đĩa
    def self.cleanup_legacy_ipc_token_file!
      legacy_fp = File.join(app_state_root, ".bridge_ipc_token")
      File.delete(legacy_fp) if File.file?(legacy_fp) && !File.symlink?(legacy_fp)
    rescue StandardError
      nil
    end

    def self.secure_hex_eq?(a_hex, b_hex)
      a = a_hex.to_s.strip.downcase
      b = b_hex.to_s.strip.downcase
      return false if a.empty? || a.bytesize != b.bytesize
      diff = 0
      a.bytes.each_with_index do |byte_val, idx|
        diff |= (byte_val ^ b.getbyte(idx))
      end
      diff == 0
    end

    def self.win_platform_os?
      !!(RUBY_PLATFORM =~ /mswin|mingw|cygwin/i) || (defined?(Gem) && Gem.win_platform?)
    end

    def self.windows_reparse_point?(path_str)
      return true if File.symlink?(path_str)
      return false unless win_platform_os? && defined?(Fiddle)
      begin
        if @win_get_file_attrs.nil? || @win_find_first_file.nil?
          kernel32 = Fiddle.dlopen("kernel32.dll")
          @win_get_file_attrs ||= Fiddle::Function.new(
            kernel32["GetFileAttributesW"],
            [Fiddle::TYPE_VOIDP],
            Fiddle::TYPE_INT
          )
          @win_find_first_file ||= Fiddle::Function.new(
            kernel32["FindFirstFileW"],
            [Fiddle::TYPE_VOIDP, Fiddle::TYPE_VOIDP],
            Fiddle::TYPE_VOIDP
          )
          @win_find_close ||= Fiddle::Function.new(
            kernel32["FindClose"],
            [Fiddle::TYPE_VOIDP],
            Fiddle::TYPE_INT
          )
        end
        wpath = (path_str.to_s.tr("/", "\\") + "\0").encode("UTF-16LE")
        attrs = @win_get_file_attrs.call(wpath)
        return false if attrs == -1 || attrs == 0xFFFFFFFF
        return false if (attrs & 0x0400) == 0

        # Chỉ chặn các liên kết chuyển hướng nguy hiểm (Symlink / Junction / MountPoint / AppExecLink),
        # KHÔNG chặn nhầm tệp đồng bộ đám mây OneDrive (IO_REPARSE_TAG_CLOUD* = 0x9000xxxx) hay nén WOF/Dedup của Windows!
        clean_s = path_str.to_s.tr("/", "\\").sub(/\\+\z/, "")
        return true if clean_s.empty? || clean_s =~ /\A[A-Za-z]:\z/
        find_buf = "\0".b * 608
        wfind = (clean_s + "\0").encode("UTF-16LE")
        h_find = @win_find_first_file.call(wfind, find_buf)
        h_addr = h_find.to_i
        return true if h_addr == 0 || h_addr == -1 || h_addr == 0xFFFFFFFFFFFFFFFF
        begin
          reparse_tag = find_buf.byteslice(36, 4).unpack("V")[0].to_i
          return true if (reparse_tag & 0x20000000) != 0
          return false if (reparse_tag & 0xFFFF0000) == 0x90000000 || reparse_tag == 0x80000017 || reparse_tag == 0x80000013
          true
        ensure
          @win_find_close.call(h_find) rescue nil
        end
      rescue StandardError
        false
      end
    rescue StandardError
      true
    end

    def self.path_has_reparse_ancestor?(target_path, stop_at_root = nil)
      clean = File.expand_path(target_path.to_s).tr("\\", "/").chomp("/")
      stop_norm = stop_at_root ? File.expand_path(stop_at_root.to_s).tr("\\", "/").chomp("/").downcase : nil
      parts = clean.split("/")
      cur = ""
      parts.each_with_index do |seg, idx|
        if idx == 0 && seg =~ /\A[A-Za-z]:\z/
          cur = "#{seg}/"
          next
        end
        cur = cur.end_with?("/") ? "#{cur}#{seg}" : (cur.empty? ? "/#{seg}" : "#{cur}/#{seg}")
        next if stop_norm && cur.chomp("/").downcase.length < stop_norm.length && stop_norm.start_with?(cur.chomp("/").downcase)
        if File.exist?(cur) || File.symlink?(cur)
          return true if windows_reparse_point?(cur)
        end
      end
      false
    rescue StandardError
      true
    end

    def self.unsafe_archive_rel_path?(rel_path)
      s = rel_path.to_s
      return true if s.empty? || s.bytesize > MAX_PAK_PATH_LEN
      return true if s.include?("\0") || s =~ /[\x00-\x1F]/
      return true if s.start_with?("/", "\\") || s.include?(":")
      norm = s.tr("\\", "/")
      segs = norm.split("/", -1)
      return true if segs.any? { |seg| seg.empty? || seg == "." || seg == ".." }
      segs.each do |seg|
        return true if seg.end_with?(".", " ")
        stem = seg.split(".", 2).first.to_s.upcase
        return true if WIN_RESERVED_NAMES.include?(stem)
      end
      false
    end

    def self.engine_base_dir
      File.join(app_state_root, "engines", ENGINE_VERSION_TAG)
    end

    def self.embedded_python_dir
      File.join(engine_base_dir, "python_embed")
    end

    def self.dpapi_init_fiddle!
      return false unless win_platform_os? && defined?(Fiddle)
      if @win_crypt_protect.nil?
        crypt32 = Fiddle.dlopen("crypt32.dll")
        kernel32 = Fiddle.dlopen("kernel32.dll")
        @win_crypt_protect = Fiddle::Function.new(
          crypt32["CryptProtectData"],
          [Fiddle::TYPE_VOIDP, Fiddle::TYPE_VOIDP, Fiddle::TYPE_VOIDP, Fiddle::TYPE_VOIDP, Fiddle::TYPE_VOIDP, Fiddle::TYPE_INT, Fiddle::TYPE_VOIDP],
          Fiddle::TYPE_INT
        )
        @win_crypt_unprotect = Fiddle::Function.new(
          crypt32["CryptUnprotectData"],
          [Fiddle::TYPE_VOIDP, Fiddle::TYPE_VOIDP, Fiddle::TYPE_VOIDP, Fiddle::TYPE_VOIDP, Fiddle::TYPE_VOIDP, Fiddle::TYPE_INT, Fiddle::TYPE_VOIDP],
          Fiddle::TYPE_INT
        )
        @win_local_free = Fiddle::Function.new(
          kernel32["LocalFree"],
          [Fiddle::TYPE_VOIDP],
          Fiddle::TYPE_VOIDP
        )
      end
      true
    rescue StandardError
      false
    end

    def self.dpapi_seal_bytes(plain_str, entropy_label = "MapSKP_TxSeal_v281")
      return nil unless dpapi_init_fiddle!
      plain_bin = plain_str.to_s.b
      ent_bin = entropy_label.to_s.b
      in_ptr = Fiddle::Pointer[plain_bin]
      ent_ptr = Fiddle::Pointer[ent_bin]
      in_blob = [plain_bin.bytesize, in_ptr.to_i].pack("L<x4Q<")
      ent_blob = [ent_bin.bytesize, ent_ptr.to_i].pack("L<x4Q<")
      out_blob = "\0".b * 16
      ok = @win_crypt_protect.call(in_blob, nil, ent_blob, nil, nil, 0x01, out_blob)
      return nil if ok == 0
      cb_out, pb_out = out_blob.unpack("L<x4Q<")
      return nil if pb_out == 0 || cb_out <= 0
      begin
        cipher = Fiddle::Pointer.new(pb_out, cb_out).to_str
        "dpapi_rb1:" + Base64.strict_encode64(cipher)
      ensure
        @win_local_free.call(pb_out) rescue nil
      end
    rescue StandardError
      nil
    end

    def self.dpapi_unseal_bytes(sealed_str, entropy_label = "MapSKP_TxSeal_v281")
      s = sealed_str.to_s.strip
      return nil unless s.start_with?("dpapi_rb1:")
      return nil unless dpapi_init_fiddle!
      cipher = Base64.strict_decode64(s.sub(/\Adpapi_rb1:/, ""))
      return nil if cipher.empty?
      ent_bin = entropy_label.to_s.b
      in_ptr = Fiddle::Pointer[cipher]
      ent_ptr = Fiddle::Pointer[ent_bin]
      in_blob = [cipher.bytesize, in_ptr.to_i].pack("L<x4Q<")
      ent_blob = [ent_bin.bytesize, ent_ptr.to_i].pack("L<x4Q<")
      out_blob = "\0".b * 16
      ok = @win_crypt_unprotect.call(in_blob, nil, ent_blob, nil, nil, 0x01, out_blob)
      return nil if ok == 0
      cb_out, pb_out = out_blob.unpack("L<x4Q<")
      return nil if pb_out == 0 || cb_out < 0
      begin
        Fiddle::Pointer.new(pb_out, cb_out).to_str
      ensure
        @win_local_free.call(pb_out) rescue nil
      end
    rescue StandardError
      nil
    end

    def self.embedded_pak_manifest_candidates(pak_file = nil)
      cands = []
      if pak_file && !pak_file.to_s.empty?
        cands << File.join(File.dirname(pak_file), "engine_rt_v2.manifest.json").tr("\\", "/")
      end
      cands << File.join(__dir__, "payload", "engine_rt_v2.manifest.json").tr("\\", "/")
      cands.uniq
    end

    def self.verify_cached_pyd_against_signed_manifest(pyd_file, cm, bridge_dir = nil, pub_hex = PINNED_PUBLISHER_ED25519_PUB_HEX)
      return false unless File.file?(pyd_file) && !windows_reparse_point?(pyd_file)
      return false unless cm.is_a?(Hash)
      signed_manifest = cm["signed_manifest"]
      return false unless signed_manifest.is_a?(Hash)

      ok_sig, _err = verify_publisher_manifest_ed25519(signed_manifest, pub_hex, expected_schema: "mapskp_update_manifest_v1")
      return false unless ok_sig
      return false unless signed_manifest["abi_tag"].to_s.strip == EXPECTED_ABI_TAG

      ch_key = cm["channel"].to_s.strip
      return false if ch_key.empty?
      ch_doc = signed_manifest["channels"].is_a?(Hash) ? signed_manifest["channels"][ch_key] : nil
      return false unless ch_doc.is_a?(Hash)

      signed_pyd_sha  = ch_doc["pyd_sha256"].to_s.strip.downcase
      signed_vlt_sha  = ch_doc["vlt_sha256"].to_s.strip.downcase
      signed_pyd_size = ch_doc["pyd_size_bytes"].to_i
      signed_pyd_abi  = ch_doc["pyd_abi"].to_s.strip
      signed_pyd_rel  = ch_doc["pyd_rel_path"].to_s.strip
      signed_build    = ch_doc["build_number"].to_i
      cat             = ch_doc["files_catalog"]

      return false unless signed_pyd_sha =~ /\A[0-9a-f]{64}\z/
      return false unless signed_vlt_sha =~ /\A[0-9a-f]{64}\z/
      return false unless signed_pyd_size > 0 && signed_build > 0
      return false unless signed_pyd_abi == EXPECTED_ABI_TAG
      return false unless signed_pyd_rel == "pyd_stage/#{EXPECTED_ABI_PYD_NAME}"
      return false unless cat.is_a?(Hash) && cat[signed_pyd_rel].is_a?(Hash)
      return false unless secure_hex_eq?(cat[signed_pyd_rel]["sha256"].to_s, signed_pyd_sha)
      return false unless cat[signed_pyd_rel]["size"].to_i == signed_pyd_size

      return false unless secure_hex_eq?(cm["pyd_sha256"].to_s, signed_pyd_sha)
      return false unless secure_hex_eq?(cm["vlt_sha256"].to_s, signed_vlt_sha)

      actual_pyd_size = File.size(pyd_file)
      return false unless actual_pyd_size == signed_pyd_size
      actual_pyd_sha = Digest::SHA256.file(pyd_file).hexdigest.downcase
      return false unless secure_hex_eq?(actual_pyd_sha, signed_pyd_sha)

      if bridge_dir && !bridge_dir.to_s.empty?
        vlt_fp = File.join(bridge_dir.to_s, "core_ip.vlt")
        return false unless File.file?(vlt_fp) && !windows_reparse_point?(vlt_fp)
        actual_vlt_sha = Digest::SHA256.file(vlt_fp).hexdigest.downcase
        return false unless secure_hex_eq?(actual_vlt_sha, signed_vlt_sha)
        plugins_root = File.expand_path("../..", bridge_dir.to_s)
        dmode = read_plugin_dist_mode(plugins_root)
        return false if !dmode.empty? && dmode != ch_key
      end
      true
    rescue StandardError
      false
    end

    def self.valid_hotpatch_pyd_installed?(pyd_file, bridge_dir = nil, pub_hex = PINNED_PUBLISHER_ED25519_PUB_HEX)
      return false unless File.file?(pyd_file) && !windows_reparse_point?(pyd_file)
      Dir.glob(File.join(hotpatch_pyd_cache_dir.tr("\\", "/"), "*", "cache_manifest.json")).each do |cm_fp|
        next if windows_reparse_point?(cm_fp) || File.size(cm_fp) > MAX_JOURNAL_BYTES
        begin
          cm = JSON.parse(File.read(cm_fp, encoding: "UTF-8"), max_nesting: 20)
          return true if verify_cached_pyd_against_signed_manifest(pyd_file, cm, bridge_dir, pub_hex)
        rescue StandardError
          next
        end
      end
      false
    rescue StandardError
      false
    end

    def self.embedded_runtime_intact?(py_dir, bridge_dir = nil, pub_hex: PINNED_PUBLISHER_ED25519_PUB_HEX)
      return false unless Dir.exist?(py_dir)
      return false if path_has_reparse_ancestor?(py_dir, app_state_root)

      signed_man_fp = File.join(py_dir, ".pak_signed_manifest.json")
      pak_manifest = nil
      migrated_from_payload = false

      if File.file?(signed_man_fp) && !windows_reparse_point?(signed_man_fp) && File.size(signed_man_fp) <= 2_097_152
        pak_manifest = JSON.parse(File.read(signed_man_fp, encoding: "UTF-8"), max_nesting: 16)
      else
        cand_man = embedded_pak_manifest_candidates.find { |fp| File.file?(fp) && !windows_reparse_point?(fp) && File.size(fp) <= 2_097_152 }
        return false unless cand_man
        pak_manifest = JSON.parse(File.read(cand_man, encoding: "UTF-8"), max_nesting: 16)
        migrated_from_payload = true
      end

      return false unless pak_manifest.is_a?(Hash)
      sig_ok, _sig_err = verify_publisher_manifest_ed25519(
        pak_manifest,
        pub_hex,
        expected_schema: "mapskp_runtime_pak_manifest_v1",
        allow_python_fallback: false
      )
      return false unless sig_ok
      return false unless pak_manifest["abi_tag"].to_s == EXPECTED_ABI_TAG

      catalog = pak_manifest["files_catalog"]
      return false unless catalog.is_a?(Hash) && !catalog.empty?

      ["pythonw.exe", "python.exe", EXPECTED_ABI_PYD_NAME].each do |req_key|
        return false unless catalog[req_key].is_a?(Hash)
      end
      return false unless catalog.keys.any? { |k| k =~ /\Apython3\d+\.dll\z/i }
      return false unless catalog.keys.any? { |k| k =~ /\Apython3\d+\.zip\z/i }
      return false unless catalog.keys.any? { |k| k =~ /\Apython3\d+\._pth\z/i }

      catalog.each do |rel_p, meta|
        rel_norm = rel_p.to_s.tr("\\", "/")
        return false if unsafe_archive_rel_path?(rel_norm)
        return false unless meta.is_a?(Hash)
        want_sha  = meta["sha256"].to_s.strip.downcase
        want_size = meta["size"].to_i
        return false unless want_sha =~ /\A[0-9a-f]{64}\z/ && want_size >= 0

        cfp = File.join(py_dir, rel_norm)
        return false unless File.file?(cfp) && !windows_reparse_point?(cfp)

        if rel_norm == EXPECTED_ABI_PYD_NAME
          if File.size(cfp) != want_size || !secure_hex_eq?(Digest::SHA256.file(cfp).hexdigest, want_sha)
            return false unless valid_hotpatch_pyd_installed?(cfp, bridge_dir, pub_hex)
          end
        else
          return false unless File.size(cfp) == want_size
          return false unless secure_hex_eq?(Digest::SHA256.file(cfp).hexdigest, want_sha)
        end
      end

      allowed_meta = {
        ".pak_signed_manifest.json" => true,
        ".pak_files_sha256.json"    => true,
        ".pak_v210_ready"           => true,
        ".pak_v281_ready"           => true,
        READY_MARKER_NAME           => true
      }
      py_norm = py_dir.to_s.tr("\\", "/").chomp("/")
      Dir.glob("#{py_norm}/**/*", File::FNM_DOTMATCH).each do |fp|
        base = File.basename(fp)
        next if base == "." || base == ".."
        return false if windows_reparse_point?(fp)
        next unless File.file?(fp)
        rel = fp[(py_norm.length + 1)..-1].to_s.tr("\\", "/")
        next if allowed_meta[rel]
        return false unless catalog.key?(rel)
      end

      if migrated_from_payload
        begin
          tmp_m = "#{signed_man_fp}.tmp_#{Process.pid}"
          File.write(tmp_m, JSON.generate(pak_manifest), mode: "w:UTF-8")
          atomic_replace_file!(tmp_m, signed_man_fp)
        rescue StandardError
          nil
        end
      end
      true
    rescue StandardError
      false
    end

    def self.atomic_replace_file!(tmp_path, dst_path)
      File.rename(tmp_path, dst_path)
    ensure
      begin
        File.delete(tmp_path) if File.file?(tmp_path) && !windows_reparse_point?(tmp_path)
      rescue StandardError
        nil
      end
    end

    def self.embedded_pak_candidates
      cands = []
      cands << File.join(__dir__, "payload", "engine_rt_v2.pak").tr("\\", "/")
      plugin_root = File.expand_path("..", __dir__).tr("\\", "/")
      cands << File.join(plugin_root, "releases", "v2.0.1_oneclick", "engine_rt_v2.pak")
      cands
    end

    def self.with_file_lock(lock_path, timeout_sec = 8.0)
      FileUtils.mkdir_p(File.dirname(lock_path))
      File.open(lock_path, File::RDWR | File::CREAT, 0o600) do |f|
        deadline = Time.now.to_f + timeout_sec.to_f
        locked = false
        while Time.now.to_f < deadline
          if f.flock(File::LOCK_EX | File::LOCK_NB)
            locked = true
            break
          end
          sleep(0.08)
        end
        return nil unless locked
        begin
          yield
        ensure
          f.flock(File::LOCK_UN) rescue nil
        end
      end
    end

    def self.unpack_embedded_pak_native!(bridge_dir = nil, pub_hex: PINNED_PUBLISHER_ED25519_PUB_HEX)
      pak_file = embedded_pak_candidates.find { |fp| File.file?(fp) && !windows_reparse_point?(fp) }
      return false unless pak_file
      return false if path_has_reparse_ancestor?(app_state_root)

      man_file = embedded_pak_manifest_candidates(pak_file).find { |fp| File.file?(fp) && !windows_reparse_point?(fp) && File.size(fp) <= 2_097_152 }
      return false unless man_file

      pak_manifest = JSON.parse(File.read(man_file, encoding: "UTF-8"), max_nesting: 16)
      sig_ok, _sig_err = verify_publisher_manifest_ed25519(
        pak_manifest,
        pub_hex,
        expected_schema: "mapskp_runtime_pak_manifest_v1",
        allow_python_fallback: false
      )
      return false unless sig_ok
      catalog = pak_manifest["files_catalog"]
      return false unless catalog.is_a?(Hash) && !catalog.empty?

      target_dir = embedded_python_dir
      ready_marker = File.join(target_dir, READY_MARKER_NAME)
      pak_sig = Digest::SHA256.file(pak_file).hexdigest.downcase

      if File.file?(ready_marker) && embedded_runtime_intact?(target_dir, bridge_dir, pub_hex: pub_hex)
        return true
      end

      return false unless secure_hex_eq?(pak_sig, pak_manifest["pak_sha256"].to_s)
      return false unless File.size(pak_file) == pak_manifest["pak_size_bytes"].to_i

      lock_fp = File.join(engine_base_dir, ".pak_unpack.lock")
      res = with_file_lock(lock_fp, 12.0) do
        if File.file?(ready_marker) && embedded_runtime_intact?(target_dir, bridge_dir, pub_hex: pub_hex)
          next true
        end

        stage_unpack = "#{target_dir}.stage_#{Process.pid}_#{SecureRandom.hex(4)}"
        begin
          FileUtils.rm_rf(stage_unpack)
          FileUtils.mkdir_p(stage_unpack)
          total_unpacked = 0
          seen_lower = {}
          unpacked_keys = []
          critical_hashes = {}

          File.open(pak_file, "rb") do |io|
            magic = io.read(9)
            return false unless magic == PAK_MAGIC

            cnt_bytes = io.read(4)
            return false unless cnt_bytes && cnt_bytes.bytesize == 4
            entry_count = cnt_bytes.unpack("V")[0].to_i
            return false if entry_count <= 0 || entry_count > MAX_PAK_ENTRIES
            return false unless entry_count == catalog.size

            entry_count.times do
              plen_bytes = io.read(2)
              raise "Truncated PAK path length" unless plen_bytes && plen_bytes.bytesize == 2
              plen = plen_bytes.unpack("v")[0].to_i
              raise "Invalid PAK path length" if plen <= 0 || plen > MAX_PAK_PATH_LEN

              rel_raw = io.read(plen)
              raise "Truncated PAK path" unless rel_raw && rel_raw.bytesize == plen
              rel_path = rel_raw.force_encoding("UTF-8")
              raise "Invalid UTF-8 in PAK path" unless rel_path.valid_encoding?
              rel_norm = rel_path.tr("\\", "/")
              raise "Unsafe PAK entry path: #{rel_norm}" if unsafe_archive_rel_path?(rel_norm)

              low_key = rel_norm.downcase
              raise "Duplicate case-insensitive PAK entry: #{rel_norm}" if seen_lower[low_key]
              seen_lower[low_key] = true

              cat_meta = catalog[rel_norm]
              raise "Unlisted PAK entry not in signed catalog: #{rel_norm}" unless cat_meta.is_a?(Hash)
              want_size = cat_meta["size"].to_i
              want_sha  = cat_meta["sha256"].to_s.strip.downcase

              clen_bytes = io.read(4)
              raise "Truncated PAK chunk size" unless clen_bytes && clen_bytes.bytesize == 4
              clen = clen_bytes.unpack("V")[0].to_i
              raise "Oversized compressed PAK entry" if clen <= 0 || clen > MAX_PAK_SINGLE_BYTES

              comp_data = io.read(clen)
              raise "Truncated PAK compressed payload" unless comp_data && comp_data.bytesize == clen

              zstream = Zlib::Inflate.new
              raw_parts = []
              raw_len = 0
              begin
                off = 0
                while off < comp_data.bytesize
                  in_slice = comp_data.byteslice(off, 65_536)
                  off += in_slice.bytesize
                  chunk_out = zstream.inflate(in_slice)
                  unless chunk_out.empty?
                    raw_len += chunk_out.bytesize
                    raise "PAK entry exceeds single-file cap" if raw_len > MAX_PAK_SINGLE_BYTES || raw_len > want_size
                    raise "PAK archive exceeds total byte cap" if (total_unpacked + raw_len) > MAX_PAK_TOTAL_BYTES
                    raw_parts << chunk_out
                  end
                end
                tail_out = zstream.finish
                if tail_out && !tail_out.empty?
                  raw_len += tail_out.bytesize
                  raise "PAK entry exceeds single-file cap" if raw_len > MAX_PAK_SINGLE_BYTES || raw_len > want_size
                  raise "PAK archive exceeds total byte cap" if (total_unpacked + raw_len) > MAX_PAK_TOTAL_BYTES
                  raw_parts << tail_out
                end
              ensure
                zstream.close rescue nil
              end

              raw_data = raw_parts.join
              raise "PAK entry size mismatch: #{rel_norm}" unless raw_data.bytesize == want_size
              got_sha = Digest::SHA256.hexdigest(raw_data).downcase
              raise "PAK entry SHA256 mismatch: #{rel_norm}" unless secure_hex_eq?(got_sha, want_sha)

              total_unpacked += raw_data.bytesize
              unpacked_keys << rel_norm

              dest_path = File.join(stage_unpack, rel_norm)
              FileUtils.mkdir_p(File.dirname(dest_path))
              File.binwrite(dest_path, raw_data)

              if ["pythonw.exe", "python.exe", EXPECTED_ABI_PYD_NAME].include?(rel_norm)
                critical_hashes[rel_norm] = got_sha
              end
            end
          end

          raise "PAK catalog set mismatch" unless unpacked_keys.sort == catalog.keys.sort

          File.write(File.join(stage_unpack, ".pak_signed_manifest.json"), JSON.generate(pak_manifest), mode: "w:UTF-8")
          File.write(File.join(stage_unpack, ".pak_files_sha256.json"), JSON.generate(critical_hashes), mode: "w:UTF-8")
          File.write(File.join(stage_unpack, READY_MARKER_NAME), pak_sig, mode: "w:UTF-8")

          if Dir.exist?(target_dir)
            old_dir = "#{target_dir}.old_#{Process.pid}"
            FileUtils.rm_rf(old_dir) rescue nil
            begin
              File.rename(target_dir, old_dir)
              File.rename(stage_unpack, target_dir)
              FileUtils.rm_rf(old_dir) rescue nil
            rescue StandardError
              FileUtils.rm_rf(stage_unpack) rescue nil
              next embedded_runtime_intact?(target_dir, bridge_dir, pub_hex: pub_hex)
            end
          else
            File.rename(stage_unpack, target_dir)
          end
          embedded_runtime_intact?(target_dir, bridge_dir, pub_hex: pub_hex)
        rescue StandardError
          FileUtils.rm_rf(stage_unpack) rescue nil
          false
        end
      end
      res ? true : false
    rescue StandardError
      false
    end

    def self.try_unpack_offline_bundle!(bridge_dir = nil, pub_hex: PINNED_PUBLISHER_ED25519_PUB_HEX)
      return true if unpack_embedded_pak_native!(bridge_dir, pub_hex: pub_hex)
      embedded_runtime_intact?(embedded_python_dir, bridge_dir, pub_hex: pub_hex)
    end

    def self.install_stamp_signature(plugins_root = nil)
      p_root = plugins_root ? File.expand_path(plugins_root.to_s) : File.expand_path("..", __dir__)
      main_fp = File.join(p_root, "mapskp", "main.rb")
      vlt_fp  = File.join(p_root, "mapskp", "bridge", "core_ip.vlt")
      prof_fp = File.join(p_root, "mapskp", "distribution_profile.json")
      m_ctime = File.file?(main_fp) ? (File.ctime(main_fp).to_i rescue 0) : 0
      m_mtime = File.file?(main_fp) ? (File.mtime(main_fp).to_i rescue 0) : 0
      v_sz    = File.file?(vlt_fp)  ? (File.size(vlt_fp).to_i rescue 0)  : 0
      p_mtime = File.file?(prof_fp) ? (File.mtime(prof_fp).to_i rescue 0) : 0
      "b#{CURRENT_BUILD_NUMBER}|mc#{m_ctime}|mm#{m_mtime}|vs#{v_sz}|pm#{p_mtime}"
    rescue StandardError
      "b#{CURRENT_BUILD_NUMBER}"
    end

    def self.consume_first_install_auto_open!(plugins_root = nil)
      prof_path = File.join(__dir__, "distribution_profile.json")
      auto_flag = true
      if File.file?(prof_path)
        begin
          prof = JSON.parse(File.read(prof_path, encoding: "UTF-8"))
          if prof.is_a?(Hash) && prof.key?("auto_open_first_install")
            auto_flag = prof["auto_open_first_install"] ? true : false
          end
        rescue StandardError
          auto_flag = true
        end
      end
      return false unless auto_flag

      p_root = plugins_root ? File.expand_path(plugins_root.to_s) : File.expand_path("..", __dir__)
      host_key = p_root.tr("\\", "/").chomp("/").downcase
      cur_sig = install_stamp_signature(p_root)
      stamps_fp = File.join(app_state_root, "welcome_stamps_v2.json")

      begin
        return false if path_has_reparse_ancestor?(stamps_fp, app_state_root)
        stamps = {}
        if File.file?(stamps_fp) && !windows_reparse_point?(stamps_fp) && File.size(stamps_fp) <= 262_144
          parsed = JSON.parse(File.read(stamps_fp, encoding: "UTF-8"), max_nesting: 8) rescue nil
          stamps = parsed if parsed.is_a?(Hash)
        end
        return false if stamps[host_key].to_s == cur_sig

        stamps[host_key] = cur_sig
        FileUtils.mkdir_p(app_state_root)
        tmp_fp = "#{stamps_fp}.tmp.#{Process.pid}.#{SecureRandom.hex(4)}"
        File.write(tmp_fp, JSON.generate(stamps), mode: "w:UTF-8")
        File.rename(tmp_fp, stamps_fp)
        legacy_marker = File.join(app_state_root, ".welcome_opened_v201")
        File.delete(legacy_marker) if File.file?(legacy_marker) && !windows_reparse_point?(legacy_marker)
        return true
      rescue StandardError
        return false
      end
    end

    def self.sketchup_exe_dir
      su_exe = Sketchup.find_support_file("SketchUp.exe").to_s
      if !su_exe.empty? && File.file?(su_exe)
        return File.dirname(su_exe).tr("\\", "/")
      end
      ""
    rescue StandardError
      ""
    end

    def self.dev_source_protected_bridge?(bridge_dir)
      bdir = bridge_dir.to_s.tr("\\", "/")
      return true if File.file?(File.join(bdir, "mode1_osm_dem_builder.py"))
      return true if File.file?(File.join(bdir, "geo_math.py"))
      proj_dir = File.expand_path("../..", bdir).tr("\\", "/")
      return true if Dir.exist?(File.join(proj_dir, "native_armor"))
      return true if Dir.exist?(File.join(proj_dir, ".git"))
      false
    rescue StandardError
      false
    end

    def self.armored_release_bridge?(bridge_dir)
      bdir = bridge_dir.to_s.tr("\\", "/")
      File.file?(File.join(bdir, "core_ip.vlt")) && !dev_source_protected_bridge?(bdir)
    end

    def self.candidate_python_bins(bridge_dir = nil, pub_hex: PINNED_PUBLISHER_ED25519_PUB_HEX, already_intact: false)
      emb_dir = embedded_python_dir
      intact_ok = already_intact ? true : try_unpack_offline_bundle!(bridge_dir, pub_hex: pub_hex)
      list = []

      if intact_ok
        pyw_emb = File.join(emb_dir, "pythonw.exe")
        py_emb  = File.join(emb_dir, "python.exe")
        list << [pyw_emb, "embedded_runtime"] if File.file?(pyw_emb)
        list << [py_emb, "embedded_runtime"] if File.file?(py_emb)
      end

      return list if bridge_dir && armored_release_bridge?(bridge_dir)

      [
        "C:/Python314/pythonw.exe",
        "C:/Python313/pythonw.exe",
        "C:/Python312/pythonw.exe",
        "C:/Python311/pythonw.exe",
        "C:/Python310/pythonw.exe"
      ].each do |sys_p|
        list << [sys_p, "system_python"] if File.file?(sys_p)
      end

      local_app = ENV["LOCALAPPDATA"].to_s.tr("\\", "/")
      unless local_app.empty?
        Dir.glob("#{local_app}/Programs/Python/Python*/pythonw.exe").sort.reverse.each do |up|
          next if up.downcase.include?("windowsapps")
          list << [up, "user_python"] if File.file?(up)
        end
      end

      path_dirs = ENV["PATH"].to_s.split(";").map { |d| d.tr("\\", "/") }
      path_dirs.each do |pd|
        next if pd.empty? || pd.downcase.include?("windowsapps")
        pw = File.join(pd, "pythonw.exe")
        pe = File.join(pd, "python.exe")
        list << [pw, "path_python"] if File.file?(pw)
        list << [pe, "path_python"] if File.file?(pe)
      end

      list.uniq { |pair| pair[0].downcase }
    end

    def self.monotonic_now
      Process.clock_gettime(Process::CLOCK_MONOTONIC)
    rescue StandardError
      Time.now.to_f
    end

    # #09: Trao đổi HTTP loopback non-blocking có trần thời gian cứng cho cả connect/write/read/toàn thao tác
    def self.loopback_http_exchange(port, raw_req, connect_timeout: 0.22, io_timeout: 0.45, max_bytes: 16_384)
      start_t = monotonic_now
      overall_deadline = start_t + connect_timeout.to_f + io_timeout.to_f
      sock = Socket.new(Socket::AF_INET, Socket::SOCK_STREAM, 0)
      begin
        sockaddr = Socket.sockaddr_in(port.to_i, "127.0.0.1")
        begin
          sock.connect_nonblock(sockaddr)
        rescue IO::WaitWritable, Errno::EINPROGRESS, Errno::EWOULDBLOCK
          rem_c = [connect_timeout.to_f, overall_deadline - monotonic_now].min
          return nil if rem_c <= 0
          _, w_ready, e_ready = IO.select(nil, [sock], [sock], rem_c)
          return nil if (!w_ready || w_ready.empty?) || (e_ready && !e_ready.empty?)
          so_err = (sock.getsockopt(Socket::SOL_SOCKET, Socket::SO_ERROR).int rescue -1)
          return nil unless so_err == 0
        end

        req_bin = raw_req.to_s.b
        written = 0
        while written < req_bin.bytesize
          rem_w = overall_deadline - monotonic_now
          return nil if rem_w <= 0
          begin
            n = sock.write_nonblock(req_bin.byteslice(written, req_bin.bytesize - written))
            written += n.to_i
          rescue IO::WaitWritable
            _, w_ready, = IO.select(nil, [sock], nil, rem_w)
            return nil unless w_ready && !w_ready.empty?
          end
        end

        buf = "".b
        expected_total_len = nil
        loop do
          if expected_total_len && buf.bytesize >= expected_total_len
            break
          end
          return nil if buf.bytesize > max_bytes
          rem_r = overall_deadline - monotonic_now
          return nil if rem_r <= 0
          begin
            chunk = sock.read_nonblock([4096, max_bytes + 1 - buf.bytesize].max)
            buf << chunk
            if expected_total_len.nil? && (hdr_idx = buf.index("\r\n\r\n"))
              hdr_End = hdr_idx + 4
              hdr_str = buf.byteslice(0, hdr_idx)
              if hdr_str =~ /^Content-Length:\s*(\d+)\s*$/i
                clen = Regexp.last_match(1).to_i
                return nil if (hdr_End + clen) > max_bytes
                expected_total_len = hdr_End + clen
              end
            end
          rescue IO::WaitReadable
            r_ready, = IO.select([sock], nil, nil, rem_r)
            return nil unless r_ready && !r_ready.empty?
          rescue EOFError
            break
          end
        end
        return nil if buf.empty? || buf.bytesize > max_bytes
        return nil if expected_total_len && buf.bytesize < expected_total_len
        buf
      rescue StandardError
        nil
      ensure
        sock.close rescue nil
      end
    end

    def self.hmac_sha256_hex(key_str, msg_str)
      if defined?(OpenSSL::HMAC)
        return OpenSSL::HMAC.hexdigest("SHA256", key_str.to_s, msg_str.to_s).downcase
      end
      k = key_str.to_s.b
      m = msg_str.to_s.b
      k = Digest::SHA256.digest(k) if k.bytesize > 64
      k = k + ("\x00".b * (64 - k.bytesize)) if k.bytesize < 64
      ipad = k.bytes.map { |b| (b ^ 0x36).chr }.join.b
      opad = k.bytes.map { |b| (b ^ 0x5c).chr }.join.b
      inner = Digest::SHA256.digest(ipad + m)
      Digest::SHA256.hexdigest(opad + inner).downcase
    end

    def self.challenge_hmac_for(port, tok, challenge_nonce, remote_pid)
      msg = "mapskp_v28_hs:#{port.to_i}:#{challenge_nonce}:#{remote_pid.to_i}"
      hmac_sha256_hex(tok.to_s, msg)
    end

    def self.build_ipc_v2_auth_header(method_str, path_str, raw_body_str, ipc_tok, peer_pid)
      ts = Time.now.to_i.to_s
      nonce = SecureRandom.hex(12)
      body_sha = Digest::SHA256.hexdigest(raw_body_str.to_s.b).downcase
      msg = "v2|#{method_str.to_s.upcase}|#{path_str}|#{ts}|#{nonce}|#{peer_pid.to_i}|#{body_sha}"
      mac = hmac_sha256_hex(ipc_tok.to_s, msg)
      ["v2.#{ts}.#{nonce}.#{mac}", nonce]
    end

    def self.probe_mapskp_bridge?(port, expected_token = nil, expected_pid = 0, connect_timeout: 0.22, io_timeout: 0.45)
      tok = expected_token.nil? ? @ipc_token.to_s : expected_token.to_s.strip
      return false if tok.bytesize < 32

      nonce = SecureRandom.hex(16)
      req = "GET /api/health HTTP/1.0\r\nHost: 127.0.0.1:#{port.to_i}\r\nX-MapSKP-Challenge: #{nonce}\r\nConnection: close\r\n\r\n"
      raw_resp = loopback_http_exchange(port.to_i, req, connect_timeout: connect_timeout, io_timeout: io_timeout, max_bytes: 16_384)
      return false unless raw_resp

      hdr_part, body_part = raw_resp.force_encoding("UTF-8").split("\r\n\r\n", 2)
      return false unless hdr_part && body_part && body_part.valid_encoding?
      status_line = hdr_part.lines.first.to_s
      return false unless status_line =~ /\AHTTP\/1\.[01]\s+200\b/

      doc = JSON.parse(body_part, max_nesting: 16)
      return false unless doc.is_a?(Hash) && doc["ok"] == true
      return false unless doc["service"].to_s == "MapSKP Hybrid Bridge"

      r_pid = doc["pid"].to_i
      return false if r_pid <= 0
      return false if expected_pid.to_i > 0 && r_pid != expected_pid.to_i

      got_hmac = doc["challenge_hmac"].to_s.strip.downcase
      return false unless got_hmac.bytesize == 64
      want_hmac = challenge_hmac_for(port.to_i, tok, nonce, r_pid)
      secure_hex_eq?(got_hmac, want_hmac)
    rescue StandardError
      false
    end

    def self.shutdown_bridge_on_quit!
      return false unless @spawned_by_self && @spawned_pid.to_i > 0 && @ipc_token.to_s.bytesize >= 32
      return false unless probe_mapskp_bridge?(@active_port, @ipc_token, @spawned_pid)
      auth_hdr, _n = build_ipc_v2_auth_header("POST", "/api/shutdown", "{}", @ipc_token, @spawned_pid)
      req = "POST /api/shutdown HTTP/1.0\r\nHost: 127.0.0.1:#{@active_port}\r\nX-MapSKP-Auth: #{auth_hdr}\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}"
      loopback_http_exchange(@active_port, req, connect_timeout: 0.18, io_timeout: 0.30, max_bytes: 4096)
      @spawned_by_self = false
      @spawned_pid = 0
      @ipc_token = ""
      true
    rescue StandardError
      false
    end

    def self.hotpatch_pyd_cache_dir
      File.join(app_state_root, "hotpatch_pyd_cache")
    end

    def self.updates_root_dir
      File.expand_path(File.join(app_state_root, "updates")).tr("\\", "/").chomp("/")
    end

    def self.safe_staged_dir?(staged_dir)
      raw = staged_dir.to_s.strip
      return false if raw.empty? || raw.include?("\0") || raw.start_with?("\\\\", "//")
      return false if raw.include?(":") && raw !~ /\A[A-Za-z]:[\/\\]/
      return false if raw.split(/[\/\\]/).include?("..")
      norm = File.expand_path(raw).tr("\\", "/").chomp("/")
      u_root = updates_root_dir
      return false unless norm.downcase.start_with?((u_root + "/").downcase)
      return false unless File.basename(norm).casecmp("staged").zero?
      return false if path_has_reparse_ancestor?(norm, app_state_root)
      Dir.exist?(norm)
    rescue StandardError
      false
    end

    # Chuẩn hóa JSON 1:1 với Python json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    def self.canonical_json_str(val)
      case val
      when Hash
        items = val.keys.map(&:to_s).sort.map do |k|
          raw_v = val.key?(k) ? val[k] : val[k.to_sym]
          "#{JSON.generate([k])[1..-2]}:#{canonical_json_str(raw_v)}"
        end
        "{#{items.join(',')}}"
      when Array
        "[#{val.map { |el| canonical_json_str(el) }.join(',')}]"
      when String
        JSON.generate([val])[1..-2]
      when Integer, Float, TrueClass, FalseClass
        JSON.generate([val])[1..-2]
      when NilClass
        "null"
      else
        raise "Unsupported canonical JSON type: #{val.class}"
      end
    end

    # #07: Xác minh chữ ký Ed25519 100% nội tiến trình (OpenSSL::PKey -> Fiddle libcrypto -> Pure-Ruby RFC 8032; 0% gọi tiến trình ngoài)
    def self.ed25519_mod_pow(base, exp, mod)
      return base.pow(exp, mod) if base.respond_to?(:pow)
      res = 1
      b = base % mod
      e = exp
      while e > 0
        res = (res * b) % mod if (e & 1) == 1
        b = (b * b) % mod
        e >>= 1
      end
      res
    end

    ED25519_P = (1 << 255) - 19 unless const_defined?(:ED25519_P)
    ED25519_L = (1 << 252) + 27742317777372353535851937790883648493 unless const_defined?(:ED25519_L)
    ED25519_D = (-121665 * ed25519_mod_pow(121666, (1 << 255) - 21, (1 << 255) - 19)) % ((1 << 255) - 19) unless const_defined?(:ED25519_D)
    ED25519_I = ed25519_mod_pow(2, ((1 << 255) - 20) / 4, (1 << 255) - 19) unless const_defined?(:ED25519_I)

    def self.ed25519_xrecover(y)
      xx = (y * y - 1) * ed25519_mod_pow(ED25519_D * y * y + 1, ED25519_P - 2, ED25519_P) % ED25519_P
      x = ed25519_mod_pow(xx, (ED25519_P + 3) / 8, ED25519_P)
      x = (x * ED25519_I) % ED25519_P if (x * x - xx) % ED25519_P != 0
      x = ED25519_P - x if x.odd?
      x
    end

    ED25519_BY = (4 * ed25519_mod_pow(5, ED25519_P - 2, ED25519_P)) % ED25519_P unless const_defined?(:ED25519_BY)
    ED25519_BX = ed25519_xrecover(ED25519_BY) unless const_defined?(:ED25519_BX)
    ED25519_B_EXT = [ED25519_BX, ED25519_BY, 1, (ED25519_BX * ED25519_BY) % ED25519_P].freeze unless const_defined?(:ED25519_B_EXT)

    def self.ed25519_ext_add(pt_p, pt_q)
      x1, y1, z1, t1 = pt_p
      x2, y2, z2, t2 = pt_q
      a = ((y1 - x1) * (y2 - x2)) % ED25519_P
      b = ((y1 + x1) * (y2 + x2)) % ED25519_P
      c = (2 * ED25519_D * t1 * t2) % ED25519_P
      d = (2 * z1 * z2) % ED25519_P
      e = (b - a) % ED25519_P
      f = (d - c) % ED25519_P
      g = (d + c) % ED25519_P
      h = (b + a) % ED25519_P
      [(e * f) % ED25519_P, (g * h) % ED25519_P, (f * g) % ED25519_P, (e * h) % ED25519_P]
    end

    def self.ed25519_ext_mul(pt, scalar)
      res = [0, 1, 1, 0]
      addend = pt
      k = scalar
      while k > 0
        res = ed25519_ext_add(res, addend) if (k & 1) == 1
        addend = ed25519_ext_add(addend, addend)
        k >>= 1
      end
      res
    end

    def self.ed25519_decode_le_int(bytes_str)
      acc = 0
      bytes_str.bytes.each_with_index { |b, idx| acc |= (b << (8 * idx)) }
      acc
    end

    def self.ed25519_decode_point(enc32)
      return nil unless enc32 && enc32.bytesize == 32
      raw_int = ed25519_decode_le_int(enc32)
      sign_x = (raw_int >> 255) & 1
      y = raw_int & ((1 << 255) - 1)
      return nil if y >= ED25519_P
      x = ed25519_xrecover(y)
      return nil if x == 0 && sign_x == 1
      x = (ED25519_P - x) % ED25519_P if (x & 1) != sign_x
      return nil if (-x * x + y * y - 1 - ED25519_D * x * x * y * y) % ED25519_P != 0
      [x, y, 1, (x * y) % ED25519_P]
    end

    def self.verify_ed25519_pure_ruby(pub_bytes, sig_bytes, msg_bytes)
      return false unless pub_bytes.bytesize == 32 && sig_bytes.bytesize == 64
      r_enc = sig_bytes.byteslice(0, 32)
      s_int = ed25519_decode_le_int(sig_bytes.byteslice(32, 32))
      return false if s_int >= ED25519_L
      pt_a = ed25519_decode_point(pub_bytes)
      pt_r = ed25519_decode_point(r_enc)
      return false unless pt_a && pt_r
      h_int = ed25519_decode_le_int(Digest::SHA512.digest(r_enc + pub_bytes + msg_bytes.b)) % ED25519_L
      lhs = ed25519_ext_mul(ED25519_B_EXT, s_int)
      rhs = ed25519_ext_add(pt_r, ed25519_ext_mul(pt_a, h_int))
      lx, ly, lz, _lt = lhs
      rx, ry, rz, _rt = rhs
      ((lx * rz - rx * lz) % ED25519_P).zero? && ((ly * rz - ry * lz) % ED25519_P).zero?
    rescue StandardError
      false
    end

    def self.verify_ed25519_fiddle_libcrypto(pub_bytes, sig_bytes, msg_bytes)
      return nil unless defined?(Fiddle)
      if @ed25519_libcrypto_ready.nil?
        lib = nil
        ["libcrypto-3-x64.dll", "libcrypto-1_1-x64.dll", "libcrypto-3.dll", "libcrypto-1_1.dll"].each do |cand|
          begin
            lib = Fiddle.dlopen(cand)
            break if lib
          rescue StandardError
            nil
          end
        end
        if lib
          begin
            @ed_fn_new_raw     = Fiddle::Function.new(lib["EVP_PKEY_new_raw_public_key"], [Fiddle::TYPE_INT, Fiddle::TYPE_VOIDP, Fiddle::TYPE_VOIDP, Fiddle::TYPE_SIZE_T], Fiddle::TYPE_VOIDP)
            @ed_fn_pkey_free   = Fiddle::Function.new(lib["EVP_PKEY_free"], [Fiddle::TYPE_VOIDP], Fiddle::TYPE_VOID)
            @ed_fn_ctx_new     = Fiddle::Function.new(lib["EVP_MD_CTX_new"], [], Fiddle::TYPE_VOIDP)
            @ed_fn_ctx_free    = Fiddle::Function.new(lib["EVP_MD_CTX_free"], [Fiddle::TYPE_VOIDP], Fiddle::TYPE_VOID)
            @ed_fn_verify_init = Fiddle::Function.new(lib["EVP_DigestVerifyInit"], [Fiddle::TYPE_VOIDP, Fiddle::TYPE_VOIDP, Fiddle::TYPE_VOIDP, Fiddle::TYPE_VOIDP, Fiddle::TYPE_VOIDP], Fiddle::TYPE_INT)
            @ed_fn_verify_shot = Fiddle::Function.new(lib["EVP_DigestVerify"], [Fiddle::TYPE_VOIDP, Fiddle::TYPE_VOIDP, Fiddle::TYPE_SIZE_T, Fiddle::TYPE_VOIDP, Fiddle::TYPE_SIZE_T], Fiddle::TYPE_INT)
            @ed25519_libcrypto_ready = true
          rescue StandardError
            @ed25519_libcrypto_ready = false
          end
        else
          @ed25519_libcrypto_ready = false
        end
      end
      return nil unless @ed25519_libcrypto_ready

      pkey = @ed_fn_new_raw.call(1087, nil, pub_bytes, pub_bytes.bytesize)
      return nil if pkey.nil? || pkey.to_i == 0
      ctx = nil
      begin
        ctx = @ed_fn_ctx_new.call
        return nil if ctx.nil? || ctx.to_i == 0
        rc_init = @ed_fn_verify_init.call(ctx, nil, nil, nil, pkey)
        return nil unless rc_init == 1
        rc_ver = @ed_fn_verify_shot.call(ctx, sig_bytes, sig_bytes.bytesize, msg_bytes, msg_bytes.bytesize)
        rc_ver == 1
      ensure
        @ed_fn_ctx_free.call(ctx) if ctx && ctx.to_i != 0
        @ed_fn_pkey_free.call(pkey) if pkey && pkey.to_i != 0
      end
    rescue StandardError
      nil
    end

    def self.verify_publisher_manifest_ed25519(
      manifest_obj,
      pub_hex = PINNED_PUBLISHER_ED25519_PUB_HEX,
      expected_schema: "mapskp_update_manifest_v1",
      allow_python_fallback: true
    )
      _ = allow_python_fallback
      return [false, "MANIFEST_NOT_HASH"] unless manifest_obj.is_a?(Hash)
      return [false, "MANIFEST_SCHEMA_INVALID"] unless manifest_obj["schema"].to_s == expected_schema.to_s

      sig_hex = manifest_obj["ed25519_sig_hex"].to_s.strip.downcase
      return [false, "ED25519_SIG_MISSING"] unless sig_hex =~ /\A[0-9a-f]{128}\z/
      clean_pub = pub_hex.to_s.strip.downcase
      return [false, "ED25519_PUB_INVALID"] unless clean_pub =~ /\A[0-9a-f]{64}\z/

      unsigned_hash = {}
      manifest_obj.each { |k, v| unsigned_hash[k.to_s] = v unless k.to_s == "ed25519_sig_hex" }
      canonical_bytes = canonical_json_str(unsigned_hash).encode("UTF-8").b
      pub_bytes = [clean_pub].pack("H*")
      sig_bytes = [sig_hex].pack("H*")

      unless ENV["MAPSKP_FORCE_ED25519_PURE_RUBY_FOR_TEST"]
        if OpenSSL::PKey.respond_to?(:read) && !ENV["MAPSKP_FORCE_ED25519_FIDDLE_FOR_TEST"]
          begin
            spki_der = ["302a300506032b6570032100#{clean_pub}"].pack("H*")
            pkey = OpenSSL::PKey.read(spki_der)
            ok = pkey.verify(nil, sig_bytes, canonical_bytes)
            return ok ? [true, "OK"] : [false, "ED25519_SIGNATURE_INVALID"]
          rescue StandardError
            nil
          end
        end

        fiddle_res = verify_ed25519_fiddle_libcrypto(pub_bytes, sig_bytes, canonical_bytes)
        unless fiddle_res.nil?
          return fiddle_res ? [true, "OK"] : [false, "ED25519_SIGNATURE_INVALID"]
        end
      end

      ok_pure = verify_ed25519_pure_ruby(pub_bytes, sig_bytes, canonical_bytes)
      ok_pure ? [true, "OK"] : [false, "ED25519_SIGNATURE_INVALID"]
    rescue StandardError => e
      [false, "ED25519_VERIFY_ERROR:#{e.message}"]
    end

    def self.parse_semver_array(ver_str)
      nums = ver_str.to_s.scan(/\d+/).first(4).map(&:to_i)
      nums << 0 while nums.length < 3
      nums
    end

    def self.version_watermark_file
      File.join(updates_root_dir, "committed_version_watermark.json")
    end

    def self.read_committed_version_watermark(current_plugin_ver = "2.8.0")
      wm_fp = version_watermark_file
      best = parse_semver_array(current_plugin_ver)
      if File.file?(wm_fp) && !windows_reparse_point?(wm_fp) && File.size(wm_fp) <= 4096
        begin
          doc = JSON.parse(File.read(wm_fp, encoding: "UTF-8"))
          cand = parse_semver_array(doc["version"].to_s) if doc.is_a?(Hash)
          best = cand if cand && (cand <=> best) > 0
        rescue StandardError
          nil
        end
      end
      best
    end

    def self.write_committed_version_watermark!(new_ver_str)
      cur_best = read_committed_version_watermark(new_ver_str)
      cand = parse_semver_array(new_ver_str)
      return if (cand <=> cur_best) < 0
      FileUtils.mkdir_p(updates_root_dir)
      tmp = "#{version_watermark_file}.tmp"
      File.write(tmp, JSON.generate({ "version" => new_ver_str.to_s, "updated_at" => Time.now.to_i }), mode: "w:UTF-8")
      atomic_replace_file!(tmp, version_watermark_file)
    rescue StandardError
      nil
    end

    def self.allowed_plugin_overlay_rel_path?(rel_p)
      return false if unsafe_archive_rel_path?(rel_p)
      norm = rel_p.to_s.tr("\\", "/")
      return true if norm == "mapskp.rb"
      return false unless norm.start_with?("mapskp/")
      ext = File.extname(norm).downcase
      return false if [".exe", ".dll", ".pyd", ".so", ".bat", ".cmd", ".ps1", ".vbs"].include?(ext)
      true
    end

    # #04: Giải nén & xác minh trực tiếp gói ZIP đã ký ngay trong bộ nhớ (0% TOCTOU qua thư mục staged/)
    def self.parse_and_verify_hotpatch_zip_bytes(zip_bytes, ch_doc)
      return [nil, "ZIP_CHANNEL_DOC_INVALID"] unless ch_doc.is_a?(Hash)
      want_zip_sha  = ch_doc["hotpatch_sha256"].to_s.strip.downcase
      want_zip_size = ch_doc["hotpatch_size_bytes"].to_i
      signed_cat    = ch_doc["files_catalog"]
      signed_pyd_sha  = ch_doc["pyd_sha256"].to_s.strip.downcase
      signed_pyd_size = ch_doc["pyd_size_bytes"].to_i
      signed_pyd_abi  = ch_doc["pyd_abi"].to_s.strip
      signed_pyd_rel  = ch_doc["pyd_rel_path"].to_s.strip
      signed_vlt_sha  = ch_doc["vlt_sha256"].to_s.strip.downcase
      signed_build    = ch_doc["build_number"].to_i

      return [nil, "MANIFEST_MISSING_SIGNED_CATALOG"] unless signed_cat.is_a?(Hash) && !signed_cat.empty?
      return [nil, "MANIFEST_MISSING_SIGNED_PYD_FIELDS"] unless signed_pyd_sha =~ /\A[0-9a-f]{64}\z/ && signed_pyd_size > 0 && signed_build > 0
      return [nil, "MANIFEST_PYD_ABI_MISMATCH"] unless signed_pyd_abi == EXPECTED_ABI_TAG
      return [nil, "MANIFEST_PYD_REL_MISMATCH"] unless signed_pyd_rel == "pyd_stage/#{EXPECTED_ABI_PYD_NAME}"
      return [nil, "ZIP_SIZE_INVALID"] if zip_bytes.nil? || zip_bytes.bytesize <= 22 || zip_bytes.bytesize > MAX_HOTPATCH_ZIP_BYTES
      return [nil, "ZIP_SIZE_MISMATCH_MANIFEST"] if want_zip_size > 0 && zip_bytes.bytesize != want_zip_size
      return [nil, "ZIP_SHA256_MISMATCH_MANIFEST"] unless secure_hex_eq?(Digest::SHA256.hexdigest(zip_bytes), want_zip_sha)

      bin = zip_bytes.b
      tail_len = [bin.bytesize, 65_557].min
      tail_off = bin.bytesize - tail_len
      rel_eocd = bin.byteslice(tail_off, tail_len).rindex("PK\x05\x06".b)
      return [nil, "ZIP_EOCD_NOT_FOUND"] unless rel_eocd
      eocd_pos = tail_off + rel_eocd
      return [nil, "ZIP_EOCD_TRUNCATED"] if (bin.bytesize - eocd_pos) < 22

      _sig, disk_no, cd_disk, disk_entries, total_entries, cd_size, cd_offset, cmt_len = bin.byteslice(eocd_pos, 22).unpack("VvvvvVVv")
      return [nil, "ZIP_MULTIDISK_OR_ZIP64_UNSUPPORTED"] unless disk_no == 0 && cd_disk == 0 && disk_entries == total_entries
      return [nil, "ZIP_ENTRY_COUNT_OUT_OF_RANGE"] if total_entries <= 0 || total_entries > 500
      return [nil, "ZIP_TRAILING_BYTES_REJECTED"] unless (eocd_pos + 22 + cmt_len) == bin.bytesize
      return [nil, "ZIP_CD_OUT_OF_BOUNDS"] if cd_offset + cd_size > eocd_pos

      mem_entries = {}
      seen_lower = {}
      total_uncomp = 0
      pyd_count = 0
      pos = cd_offset

      total_entries.times do
        return [nil, "ZIP_CD_ENTRY_TRUNCATED"] if (pos + 46) > (cd_offset + cd_size)
        cd_sig, _vm, _vn, gp_flag, comp_method, _mt, _md, crc32, comp_size, uncomp_size, fn_len, extra_len, fcmt_len, _ds, _ia, _ea, lfh_off =
          bin.byteslice(pos, 46).unpack("VvvvvvvVVVvvvvvVV")
        return [nil, "ZIP_CD_BAD_SIGNATURE"] unless cd_sig == 0x02014b50
        return [nil, "ZIP_ENCRYPTED_ENTRY_REJECTED"] if (gp_flag & 0x01) != 0

        pos += 46
        return [nil, "ZIP_CD_NAME_TRUNCATED"] if (pos + fn_len + extra_len + fcmt_len) > (cd_offset + cd_size)
        raw_name = bin.byteslice(pos, fn_len).force_encoding("UTF-8")
        return [nil, "ZIP_NAME_UTF8_INVALID"] unless raw_name.valid_encoding?
        pos += fn_len + extra_len + fcmt_len

        next if raw_name.end_with?("/")
        rel_norm = raw_name.tr("\\", "/")
        return [nil, "ZIP_UNSAFE_PATH:#{rel_norm}"] if unsafe_archive_rel_path?(rel_norm)

        low_k = rel_norm.downcase
        return [nil, "ZIP_DUPLICATE_ENTRY:#{rel_norm}"] if seen_lower[low_k]
        seen_lower[low_k] = true

        if rel_norm.start_with?("plugin_root/")
          plug_rel = rel_norm.sub(/\Aplugin_root\//, "")
          return [nil, "ZIP_DISALLOWED_PLUGIN_FILE:#{plug_rel}"] unless allowed_plugin_overlay_rel_path?(plug_rel)
        elsif rel_norm.start_with?("pyd_stage/")
          pyd_rel = rel_norm.sub(/\Apyd_stage\//, "")
          return [nil, "ZIP_DISALLOWED_PYD_FILE:#{pyd_rel}"] unless pyd_rel == EXPECTED_ABI_PYD_NAME
          pyd_count += 1
        else
          return [nil, "ZIP_UNEXPECTED_TOP_DIR:#{rel_norm}"]
        end

        cat_item = signed_cat[rel_norm]
        return [nil, "ZIP_ENTRY_NOT_IN_SIGNED_CATALOG:#{rel_norm}"] unless cat_item.is_a?(Hash)
        want_f_sha  = cat_item["sha256"].to_s.strip.downcase
        want_f_size = cat_item["size"].to_i
        return [nil, "ZIP_UNCOMP_SIZE_CAP:#{rel_norm}"] if uncomp_size > MAX_HOTPATCH_SINGLE_BYTES || uncomp_size != want_f_size
        return [nil, "ZIP_COMP_SIZE_CAP:#{rel_norm}"] if comp_size > MAX_HOTPATCH_SINGLE_BYTES

        return [nil, "ZIP_LFH_OUT_OF_BOUNDS"] if (lfh_off + 30) > cd_offset
        l_sig, _lvn, _lgp, l_method, _lmt, _lmd, _lcrc, _lcsz, _lusz, l_fn_len, l_ex_len =
          bin.byteslice(lfh_off, 30).unpack("VvvvvvVVVvv")
        return [nil, "ZIP_LFH_BAD_SIGNATURE"] unless l_sig == 0x04034b50 && l_method == comp_method
        data_pos = lfh_off + 30 + l_fn_len + l_ex_len
        return [nil, "ZIP_DATA_OUT_OF_BOUNDS"] if (data_pos + comp_size) > cd_offset

        comp_slice = bin.byteslice(data_pos, comp_size)
        raw_data = nil
        if comp_method == 0
          raw_data = comp_slice
        elsif comp_method == 8
          z = Zlib::Inflate.new(-Zlib::MAX_WBITS)
          parts = []
          acc = 0
          begin
            soff = 0
            while soff < comp_slice.bytesize
              sl = comp_slice.byteslice(soff, 65_536)
              soff += sl.bytesize
              out_c = z.inflate(sl)
              unless out_c.empty?
                acc += out_c.bytesize
                return [nil, "ZIP_INFLATE_SINGLE_CAP"] if acc > MAX_HOTPATCH_SINGLE_BYTES || acc > want_f_size
                return [nil, "ZIP_INFLATE_TOTAL_CAP"] if (total_uncomp + acc) > MAX_HOTPATCH_TOTAL_BYTES
                parts << out_c
              end
            end
            tail_c = z.finish
            if tail_c && !tail_c.empty?
              acc += tail_c.bytesize
              return [nil, "ZIP_INFLATE_SINGLE_CAP"] if acc > MAX_HOTPATCH_SINGLE_BYTES || acc > want_f_size
              return [nil, "ZIP_INFLATE_TOTAL_CAP"] if (total_uncomp + acc) > MAX_HOTPATCH_TOTAL_BYTES
              parts << tail_c
            end
          ensure
            z.close rescue nil
          end
          raw_data = parts.join
        else
          return [nil, "ZIP_UNSUPPORTED_METHOD:#{comp_method}"]
        end

        return [nil, "ZIP_SIZE_MISMATCH:#{rel_norm}"] unless raw_data.bytesize == uncomp_size
        return [nil, "ZIP_CRC32_MISMATCH:#{rel_norm}"] unless Zlib.crc32(raw_data) == crc32
        got_sha = Digest::SHA256.hexdigest(raw_data).downcase
        return [nil, "ZIP_CATALOG_SHA_MISMATCH:#{rel_norm}"] unless secure_hex_eq?(got_sha, want_f_sha)

        total_uncomp += raw_data.bytesize
        return [nil, "ZIP_TOTAL_CAP_EXCEEDED"] if total_uncomp > MAX_HOTPATCH_TOTAL_BYTES
        mem_entries[rel_norm] = raw_data.b.freeze
      end

      return [nil, "ZIP_AMBIGUOUS_PYD_COUNT"] unless pyd_count == 1
      return [nil, "ZIP_CATALOG_SET_MISMATCH"] unless mem_entries.keys.sort == signed_cat.keys.sort

      vlt_bytes = mem_entries["plugin_root/mapskp/bridge/core_ip.vlt"]
      pyd_bytes = mem_entries[signed_pyd_rel]
      return [nil, "ZIP_CORE_COMPONENTS_MISSING"] unless vlt_bytes && pyd_bytes
      return [nil, "ZIP_VLT_SHA_MISMATCH"] unless secure_hex_eq?(Digest::SHA256.hexdigest(vlt_bytes), signed_vlt_sha)
      return [nil, "ZIP_PYD_SHA_MISMATCH"] unless secure_hex_eq?(Digest::SHA256.hexdigest(pyd_bytes), signed_pyd_sha) && pyd_bytes.bytesize == signed_pyd_size

      [mem_entries.freeze, "OK"]
    rescue StandardError => e
      [nil, "ZIP_PARSE_ERROR:#{e.message}"]
    end

    # #03 & #04: Xác minh chữ ký Ed25519 + files_catalog + HMAC phiên + đối chiếu ZIP gốc 1:1
    def self.verify_staged_files_integrity!(s_dir, ready_meta, active_ipc_tok = nil, pub_hex = PINNED_PUBLISHER_ED25519_PUB_HEX)
      return [false, "STAGED_META_INVALID"] unless ready_meta.is_a?(Hash)
      files_map = ready_meta["files_sha256"]
      return [false, "STAGED_FILES_MAP_MISSING"] unless files_map.is_a?(Hash) && !files_map.empty?

      latest_ver = ready_meta["latest_version"].to_s.strip
      ch_key     = ready_meta["channel"].to_s.strip
      upd_job_id = ready_meta["update_job_id"].to_s.strip
      hp_sha_m   = ready_meta["hotpatch_sha256"].to_s.strip.downcase
      vlt_sha_m  = ready_meta["vlt_sha256"].to_s.strip.downcase
      pyd_sha_m  = ready_meta["pyd_sha256"].to_s.strip.downcase
      ipc_hmac   = ready_meta["ipc_hmac"].to_s.strip.downcase

      tok = active_ipc_tok.nil? ? @ipc_token.to_s.strip : active_ipc_tok.to_s.strip
      return [false, "STAGED_IPC_TOKEN_MISSING"] if tok.bytesize < 32
      return [false, "STAGED_IPC_HMAC_MISSING"] unless ipc_hmac =~ /\A[0-9a-f]{64}\z/

      sorted_pairs = files_map.keys.sort.map { |k| "#{k}:#{files_map[k].to_s.downcase}" }.join("|")
      hmac_msg = "#{upd_job_id}|#{latest_ver}|#{ch_key}|#{hp_sha_m}|#{vlt_sha_m}|#{pyd_sha_m}|#{sorted_pairs}"
      calc_hmac = hmac_sha256_hex(tok, hmac_msg)
      return [false, "STAGED_IPC_HMAC_MISMATCH"] unless secure_hex_eq?(calc_hmac, ipc_hmac)

      signed_manifest = ready_meta["signed_manifest"]
      sig_ok, sig_err = verify_publisher_manifest_ed25519(signed_manifest, pub_hex, expected_schema: "mapskp_update_manifest_v1")
      return [false, sig_err] unless sig_ok
      return [false, "MANIFEST_VERSION_MISMATCH"] unless signed_manifest["latest_version"].to_s.strip == latest_ver
      return [false, "MANIFEST_ABI_MISMATCH"] unless signed_manifest["abi_tag"].to_s.strip == EXPECTED_ABI_TAG

      ch_doc = (signed_manifest["channels"].is_a?(Hash) ? signed_manifest["channels"][ch_key] : nil)
      return [false, "MANIFEST_CHANNEL_MISSING"] unless ch_doc.is_a?(Hash)
      return [false, "MANIFEST_ZIP_HASH_MISMATCH"] unless secure_hex_eq?(ch_doc["hotpatch_sha256"].to_s, hp_sha_m)
      return [false, "MANIFEST_VLT_HASH_MISMATCH"] unless secure_hex_eq?(ch_doc["vlt_sha256"].to_s, vlt_sha_m)
      return [false, "MANIFEST_PYD_HASH_MISMATCH"] unless secure_hex_eq?(ch_doc["pyd_sha256"].to_s, pyd_sha_m)

      signed_cat = ch_doc["files_catalog"]
      return [false, "MANIFEST_SIGNED_CATALOG_MISSING"] unless signed_cat.is_a?(Hash) && !signed_cat.empty?

      zip_on_disk = File.join(File.dirname(s_dir), "hotpatch_#{ch_key}.zip")
      return [false, "STAGED_SIGNED_ZIP_MISSING"] unless File.file?(zip_on_disk) && !windows_reparse_point?(zip_on_disk)
      return [false, "STAGED_SIGNED_ZIP_OVERSIZED"] if File.size(zip_on_disk) > MAX_HOTPATCH_ZIP_BYTES
      zip_bytes = File.binread(zip_on_disk)
      return [false, "STAGED_SIGNED_ZIP_TAMPERED"] unless secure_hex_eq?(Digest::SHA256.hexdigest(zip_bytes), hp_sha_m)

      mem_entries, z_err = parse_and_verify_hotpatch_zip_bytes(zip_bytes, ch_doc)
      return [false, z_err] unless mem_entries

      return [false, "STAGED_REPARSE_DETECTED"] if path_has_reparse_ancestor?(s_dir, app_state_root)
      actual_files = []
      pyd_count = 0
      ["plugin_root", "pyd_stage"].each do |sub|
        sub_dir = File.join(s_dir, sub)
        next unless Dir.exist?(sub_dir)
        return [false, "STAGED_SUBDIR_REPARSE"] if windows_reparse_point?(sub_dir)
        Dir.glob("#{sub_dir.tr('\\', '/')}/**/*", File::FNM_DOTMATCH).each do |p|
          base = File.basename(p)
          next if base == "." || base == ".."
          return [false, "STAGED_SYMLINK_REJECTED"] if windows_reparse_point?(p)
          if File.file?(p)
            rel = p[(s_dir.length + 1)..-1].to_s.tr("\\", "/")
            if sub == "plugin_root"
              plug_rel = rel.sub(/\Aplugin_root\//, "")
              return [false, "STAGED_DISALLOWED_PLUGIN_TARGET:#{plug_rel}"] unless allowed_plugin_overlay_rel_path?(plug_rel)
            elsif sub == "pyd_stage"
              pyd_rel = rel.sub(/\Apyd_stage\//, "")
              return [false, "STAGED_DISALLOWED_PYD_NAME:#{pyd_rel}"] unless pyd_rel == EXPECTED_ABI_PYD_NAME
              pyd_count += 1
            end
            actual_files << rel
          end
        end
      end
      return [false, "STAGED_AMBIGUOUS_PYD_COUNT"] unless pyd_count == 1

      expected_keys = signed_cat.keys.map { |k| k.to_s.tr("\\", "/") }.sort
      return [false, "STAGED_FILE_SET_MISMATCH"] unless actual_files.sort == expected_keys && files_map.keys.map { |k| k.to_s.tr("\\", "/") }.sort == expected_keys

      signed_cat.each do |rel_p, cat_meta|
        clean_rel = rel_p.to_s.tr("\\", "/")
        return [false, "STAGED_REL_PATH_UNSAFE"] if unsafe_archive_rel_path?(clean_rel)
        full_p = File.join(s_dir, clean_rel)
        return [false, "STAGED_FILE_MISSING:#{clean_rel}"] unless File.file?(full_p) && !windows_reparse_point?(full_p)
        return [false, "STAGED_FILE_SIZE_MISMATCH:#{clean_rel}"] unless File.size(full_p) == cat_meta["size"].to_i
        got_sha = Digest::SHA256.file(full_p).hexdigest.downcase
        return [false, "STAGED_FILE_SHA256_MISMATCH:#{clean_rel}"] unless secure_hex_eq?(got_sha, cat_meta["sha256"].to_s)
        return [false, "STAGED_META_HASH_MISMATCH:#{clean_rel}"] unless secure_hex_eq?(got_sha, files_map[clean_rel].to_s)
      end

      [true, "OK", mem_entries, zip_bytes.freeze, ch_doc]
    rescue StandardError => e
      [false, "STAGED_VERIFY_ERROR:#{e.message}"]
    end

    # #03: Đồng bộ cache .pyd đối chiếu trực tiếp chữ ký Ed25519 trên bytes sẽ nạp
    def self.sync_cached_hotpatch_pyd!(bridge_dir, pub_hex = PINNED_PUBLISHER_ED25519_PUB_HEX)
      vlt_path = File.join(bridge_dir.to_s, "core_ip.vlt")
      return false unless File.file?(vlt_path) && !windows_reparse_point?(vlt_path)

      vlt_sha = Digest::SHA256.file(vlt_path).hexdigest.downcase
      cache_slot = File.join(hotpatch_pyd_cache_dir, vlt_sha)
      return false unless Dir.exist?(cache_slot) && !path_has_reparse_ancestor?(cache_slot, app_state_root)

      cm_path = File.join(cache_slot, "cache_manifest.json")
      src_pyd = File.join(cache_slot, EXPECTED_ABI_PYD_NAME)
      return false unless File.file?(cm_path) && !windows_reparse_point?(cm_path) && File.size(cm_path) <= MAX_JOURNAL_BYTES
      return false unless File.file?(src_pyd) && !windows_reparse_point?(src_pyd)

      cm = JSON.parse(File.read(cm_path, encoding: "UTF-8"), max_nesting: 20)
      return false unless verify_cached_pyd_against_signed_manifest(src_pyd, cm, bridge_dir, pub_hex)

      ch_doc = cm["signed_manifest"]["channels"][cm["channel"].to_s.strip]
      signed_pyd_sha  = ch_doc["pyd_sha256"].to_s.strip.downcase
      signed_pyd_size = ch_doc["pyd_size_bytes"].to_i

      raw_pyd_bytes = File.binread(src_pyd)
      return false unless raw_pyd_bytes.bytesize == signed_pyd_size
      return false unless secure_hex_eq?(Digest::SHA256.hexdigest(raw_pyd_bytes), signed_pyd_sha)

      dest_dir = embedded_python_dir
      FileUtils.mkdir_p(dest_dir)
      dest_pyd = File.join(dest_dir, EXPECTED_ABI_PYD_NAME)
      if !File.file?(dest_pyd) || File.size(dest_pyd) != signed_pyd_size || !secure_hex_eq?(Digest::SHA256.file(dest_pyd).hexdigest, signed_pyd_sha)
        tmp_pyd = "#{dest_pyd}.sync_tmp_#{Process.pid}"
        File.binwrite(tmp_pyd, raw_pyd_bytes)
        atomic_replace_file!(tmp_pyd, dest_pyd)
      end
      File.size(dest_pyd) == signed_pyd_size && secure_hex_eq?(Digest::SHA256.file(dest_pyd).hexdigest, signed_pyd_sha)
    rescue StandardError
      false
    end

    def self.force_shutdown_bridge_for_update!
      return true unless @spawned_by_self && @spawned_pid.to_i > 0 && @ipc_token.to_s.bytesize >= 32
      begin
        if probe_mapskp_bridge?(@active_port, @ipc_token, @spawned_pid)
          auth_hdr, _n = build_ipc_v2_auth_header("POST", "/api/shutdown", "{}", @ipc_token, @spawned_pid)
          req = "POST /api/shutdown HTTP/1.0\r\nHost: 127.0.0.1:#{@active_port}\r\nX-MapSKP-Auth: #{auth_hdr}\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}"
          loopback_http_exchange(@active_port, req, connect_timeout: 0.22, io_timeout: 0.35, max_bytes: 4096)
        end
      rescue StandardError
        nil
      end
      @spawned_by_self = false
      @spawned_pid = 0
      25.times do
        return true if port_free?(@active_port)
        sleep(0.08)
      end
      port_free?(@active_port)
    end

    def self.read_plugin_dist_mode(plugins_root)
      prof_path = File.join(plugins_root, "mapskp", "distribution_profile.json")
      return "" unless File.file?(prof_path)
      prof = JSON.parse(File.read(prof_path, encoding: "UTF-8"))
      prof.is_a?(Hash) ? prof["distribution_mode"].to_s.strip : ""
    rescue StandardError
      ""
    end

    def self.read_plugin_version(plugins_root)
      prof_path = File.join(plugins_root, "mapskp", "distribution_profile.json")
      if File.file?(prof_path)
        prof = JSON.parse(File.read(prof_path, encoding: "UTF-8"))
        return prof["version"].to_s.strip if prof.is_a?(Hash) && !prof["version"].to_s.strip.empty?
      end
      "2.8.1"
    rescue StandardError
      "2.8.1"
    end

    def self.discover_compatible_plugin_roots(primary_plugins_root, _expected_dist_mode)
      [primary_plugins_root.to_s.tr("\\", "/").chomp("/")]
    end

    def self.snapshot_plugin_tree_hashes(plugins_root)
      hashes = {}
      rb_entry = File.join(plugins_root, "mapskp.rb")
      hashes["mapskp.rb"] = Digest::SHA256.file(rb_entry).hexdigest.downcase if File.file?(rb_entry) && !windows_reparse_point?(rb_entry)
      mp_dir = File.join(plugins_root, "mapskp")
      if Dir.exist?(mp_dir) && !windows_reparse_point?(mp_dir)
        Dir.glob("#{mp_dir.tr('\\', '/')}/**/*", File::FNM_DOTMATCH).each do |fp|
          base = File.basename(fp)
          next if base == "." || base == ".."
          next if windows_reparse_point?(fp)
          next unless File.file?(fp)
          rel = fp[(plugins_root.length + 1)..-1].to_s.tr("\\", "/")
          hashes[rel] = Digest::SHA256.file(fp).hexdigest.downcase
        end
      end
      hashes
    end

    def self.overlay_directory_files!(src_root, dst_root)
      s_norm = src_root.to_s.tr("\\", "/").chomp("/")
      Dir.glob("#{s_norm}/**/*", File::FNM_DOTMATCH).each do |src_item|
        base = File.basename(src_item)
        next if base == "." || base == ".."
        raise "Unsafe symlink in overlay source" if windows_reparse_point?(src_item)
        rel = src_item[(s_norm.length + 1)..-1]
        next if rel.nil? || rel.empty?
        raise "Unsafe relative path in overlay: #{rel}" if unsafe_archive_rel_path?(rel)
        dst_item = File.join(dst_root, rel)
        raise "Unsafe reparse target in overlay: #{dst_item}" if File.exist?(dst_item) && windows_reparse_point?(dst_item)
        if File.directory?(src_item)
          FileUtils.mkdir_p(dst_item)
        elsif File.file?(src_item)
          FileUtils.mkdir_p(File.dirname(dst_item))
          tmp_item = "#{dst_item}.upd_tmp_#{Process.pid}"
          File.binwrite(tmp_item, File.binread(src_item))
          atomic_replace_file!(tmp_item, dst_item)
        end
      end
    end

    # #05: 2-pass strict overlay — chỉ cho phép mapskp.rb và mapskp/** hợp lệ; phát hiện bất kỳ tệp lạ nào là chặn trước khi ghi!
    def self.validate_strict_plugin_backup_tree(src_root, expected_hashes = nil)
      s_norm = src_root.to_s.tr("\\", "/").chomp("/")
      return [false, "BACKUP_ROOT_MISSING"] unless Dir.exist?(s_norm) && !path_has_reparse_ancestor?(s_norm, app_state_root)
      found_hashes = {}
      Dir.glob("#{s_norm}/**/*", File::FNM_DOTMATCH).each do |src_item|
        base = File.basename(src_item)
        next if base == "." || base == ".."
        return [false, "BACKUP_REPARSE_REJECTED"] if windows_reparse_point?(src_item)
        rel = src_item[(s_norm.length + 1)..-1].to_s.tr("\\", "/")
        next if rel.empty?
        return [false, "BACKUP_UNSAFE_REL:#{rel}"] if unsafe_archive_rel_path?(rel)
        if File.directory?(src_item)
          unless rel == "mapskp" || rel.start_with?("mapskp/")
            return [false, "BACKUP_FOREIGN_DIR_REJECTED:#{rel}"]
          end
        elsif File.file?(src_item)
          unless allowed_plugin_overlay_rel_path?(rel)
            return [false, "BACKUP_FOREIGN_FILE_REJECTED:#{rel}"]
          end
          found_hashes[rel] = Digest::SHA256.file(src_item).hexdigest.downcase
        else
          return [false, "BACKUP_SPECIAL_FILE_REJECTED:#{rel}"]
        end
      end
      if expected_hashes.is_a?(Hash)
        norm_exp = {}
        expected_hashes.each do |k, v|
          rk = k.to_s.tr("\\", "/")
          return [false, "EXPECTED_HASH_FOREIGN_PATH:#{rk}"] unless allowed_plugin_overlay_rel_path?(rk)
          norm_exp[rk] = v.to_s.strip.downcase
        end
        return [false, "BACKUP_HASH_SET_MISMATCH"] unless found_hashes == norm_exp
      end
      [true, "OK"]
    rescue StandardError => e
      [false, "BACKUP_VALIDATE_ERROR:#{e.message}"]
    end

    def self.overlay_plugin_tree_strict!(src_root, dst_plugins_root, expected_hashes = nil)
      ok_tree, err_tree = validate_strict_plugin_backup_tree(src_root, expected_hashes)
      raise err_tree unless ok_tree
      raise "Unsafe reparse in target Plugins root" if path_has_reparse_ancestor?(dst_plugins_root)

      s_norm = src_root.to_s.tr("\\", "/").chomp("/")
      Dir.glob("#{s_norm}/**/*", File::FNM_DOTMATCH).each do |src_item|
        base = File.basename(src_item)
        next if base == "." || base == ".."
        rel = src_item[(s_norm.length + 1)..-1].to_s.tr("\\", "/")
        next if rel.empty?
        dst_item = File.join(dst_plugins_root, rel)
        raise "Unsafe reparse target in Plugins: #{rel}" if (File.exist?(dst_item) || File.symlink?(dst_item)) && windows_reparse_point?(dst_item)
        if File.directory?(src_item)
          FileUtils.mkdir_p(dst_item)
        elsif File.file?(src_item)
          raise "Disallowed overlay target: #{rel}" unless allowed_plugin_overlay_rel_path?(rel)
          FileUtils.mkdir_p(File.dirname(dst_item))
          tmp_item = "#{dst_item}.upd_tmp_#{Process.pid}"
          File.binwrite(tmp_item, File.binread(src_item))
          atomic_replace_file!(tmp_item, dst_item)
        end
      end
      true
    end

    def self.write_verified_plugin_entries_from_memory!(mem_entries, dst_plugins_root)
      raise "Unsafe reparse in target Plugins root" if path_has_reparse_ancestor?(dst_plugins_root)
      mem_entries.each do |arc_rel, raw_bytes|
        next unless arc_rel.start_with?("plugin_root/")
        plug_rel = arc_rel.sub(/\Aplugin_root\//, "")
        raise "Disallowed memory overlay target: #{plug_rel}" unless allowed_plugin_overlay_rel_path?(plug_rel)
        dst_item = File.join(dst_plugins_root, plug_rel)
        raise "Unsafe reparse target: #{plug_rel}" if (File.exist?(dst_item) || File.symlink?(dst_item)) && windows_reparse_point?(dst_item)
        parent_d = File.dirname(dst_item)
        raise "Unsafe reparse parent: #{plug_rel}" if (File.exist?(parent_d) || File.symlink?(parent_d)) && windows_reparse_point?(parent_d)
        FileUtils.mkdir_p(parent_d)
        tmp_item = "#{dst_item}.upd_tmp_#{Process.pid}"
        File.binwrite(tmp_item, raw_bytes)
        atomic_replace_file!(tmp_item, dst_item)
      end
      true
    end

    def self.tx_authority_file
      File.join(updates_root_dir, "tx_authority.dpapi")
    end

    def self.read_tx_authority
      fp = tx_authority_file
      if !File.exist?(fp) && !File.symlink?(fp)
        return [true, { "seq" => 0, "active_tx_id" => "", "pending_tx_id" => "", "recovery_required_tx_id" => "" }]
      end
      return [false, nil] if windows_reparse_point?(fp) || !File.file?(fp) || File.size(fp) > 65_536
      raw = File.read(fp, encoding: "UTF-8").strip
      plain = dpapi_unseal_bytes(raw, "MapSKP_TxAuthority_v281")
      return [false, nil] unless plain
      doc = JSON.parse(plain.force_encoding("UTF-8"), max_nesting: 8)
      return [false, nil] unless doc.is_a?(Hash)
      [true, doc]
    rescue StandardError
      [false, nil]
    end

    def self.write_tx_authority!(auth_hash)
      FileUtils.mkdir_p(updates_root_dir)
      sealed = dpapi_seal_bytes(canonical_json_str(auth_hash), "MapSKP_TxAuthority_v281")
      raise "DPAPI authority seal failed" unless sealed
      fp = tx_authority_file
      tmp = "#{fp}.tmp_#{Process.pid}"
      File.write(tmp, sealed, mode: "w:UTF-8")
      atomic_replace_file!(tmp, fp)
      true
    end

    def self.write_tx_journal!(journal_path, state_obj)
      FileUtils.mkdir_p(File.dirname(journal_path))
      unsigned = {}
      state_obj.each { |k, v| unsigned[k.to_s] = v unless k.to_s == "journal_dpapi_seal" }
      seal = dpapi_seal_bytes(canonical_json_str(unsigned), "MapSKP_TxJournal_v281")
      raise "DPAPI journal seal failed" unless seal
      full_obj = unsigned.merge("journal_dpapi_seal" => seal)
      tmp = "#{journal_path}.tmp_#{Process.pid}"
      File.write(tmp, JSON.pretty_generate(full_obj), mode: "w:UTF-8")
      atomic_replace_file!(tmp, journal_path)
    end

    def self.verify_sealed_tx_journal(jdoc)
      return false unless jdoc.is_a?(Hash)
      seal = jdoc["journal_dpapi_seal"].to_s
      return false if seal.empty?
      plain = dpapi_unseal_bytes(seal, "MapSKP_TxJournal_v281")
      return false unless plain
      unsigned = {}
      jdoc.each { |k, v| unsigned[k.to_s] = v unless k.to_s == "journal_dpapi_seal" }
      plain.b == canonical_json_str(unsigned).b
    rescue StandardError
      false
    end

    def self.valid_plugins_root_contract?(plugins_root)
      return false if plugins_root.nil? || plugins_root.to_s.strip.empty?
      norm = File.expand_path(plugins_root.to_s).tr("\\", "/").chomp("/")
      bname = File.basename(norm).downcase
      return false if bname == "bridge"
      return false if bname == "mapskp" && (File.file?(File.join(norm, "main.rb")) || Dir.exist?(File.join(norm, "bridge")))
      true
    rescue StandardError
      false
    end

    def self.reset_recovery_after_clean_rbz_install!
      lock_fp = File.join(updates_root_dir, ".update_tx.lock")
      with_file_lock(lock_fp, 5.0) do
        ok_a, auth = read_tx_authority
        next_seq = (ok_a && auth.is_a?(Hash) ? auth["seq"].to_i : 0) + 1
        write_tx_authority!({
          "seq"                     => next_seq,
          "active_tx_id"            => "",
          "pending_tx_id"           => "",
          "recovery_required_tx_id" => "",
          "updated_at"              => Time.now.to_i
        })
        j_fp = File.join(updates_root_dir, "tx_journal.json")
        File.delete(j_fp) if File.file?(j_fp) && !windows_reparse_point?(j_fp)
        pend_dir = File.join(updates_root_dir, "pending_activation")
        FileUtils.rm_rf(pend_dir) if Dir.exist?(pend_dir)
        true
      end
    rescue StandardError
      false
    end

    def self.resolve_staged_dir_from_job_id(update_job_id, active_ipc_tok = nil)
      jid = update_job_id.to_s.strip
      return [nil, "UPDATE_JOB_ID_INVALID"] unless jid =~ /\Aupd_[A-Za-z0-9._-]{3,48}\z/
      job_fp = File.join(updates_root_dir, "jobs", "#{jid}.json")
      return [nil, "UPDATE_JOB_NOT_FOUND"] unless File.file?(job_fp) && !windows_reparse_point?(job_fp) && File.size(job_fp) <= 65_536

      jdoc = JSON.parse(File.read(job_fp, encoding: "UTF-8"))
      return [nil, "UPDATE_JOB_CORRUPT"] unless jdoc.is_a?(Hash) && jdoc["update_job_id"].to_s == jid
      return [nil, "UPDATE_JOB_ALREADY_CONSUMED"] if jdoc["consumed"] == true

      tok = active_ipc_tok.nil? ? @ipc_token.to_s.strip : active_ipc_tok.to_s.strip
      return [nil, "UPDATE_JOB_IPC_MISSING"] if tok.bytesize < 32
      want_mac = hmac_sha256_hex(tok, "job:#{jid}|#{jdoc['staged_dir']}|#{jdoc['latest_version']}")
      return [nil, "UPDATE_JOB_HMAC_MISMATCH"] unless secure_hex_eq?(jdoc["job_hmac"].to_s, want_mac)

      [jdoc["staged_dir"].to_s, "OK", job_fp, jdoc]
    rescue StandardError => e
      [nil, "UPDATE_JOB_ERROR:#{e.message}"]
    end

    # #02, #05, #06: Recovery kiểm tra khóa giao dịch, chống replay journal, khôi phục đủ .pyd/cache/plugin/watermark & chặn khi lỗi
    def self.recover_interrupted_update_if_needed!(primary_plugins_root)
      unless valid_plugins_root_contract?(primary_plugins_root)
        return {
          "ok"                => false,
          "recovered"         => false,
          "recovery_required" => true,
          "state"             => "RECOVERY_REQUIRED",
          "code"              => "INVALID_PLUGINS_ROOT_CONTRACT"
        }
      end

      if @in_active_update_tx_id
        return { "ok" => true, "recovered" => false, "active_tx_locked" => true, "code" => "TX_ACTIVE_IN_PROCESS" }
      end

      lock_fp = File.join(updates_root_dir, ".update_tx.lock")
      FileUtils.mkdir_p(File.dirname(lock_fp))
      File.open(lock_fp, File::RDWR | File::CREAT, 0o600) do |lf|
        unless lf.flock(File::LOCK_EX | File::LOCK_NB)
          return { "ok" => true, "recovered" => false, "active_tx_locked" => true, "code" => "TX_ACTIVE_LOCKED" }
        end
        begin
          return perform_locked_startup_recovery!(primary_plugins_root)
        ensure
          lf.flock(File::LOCK_UN) rescue nil
        end
      end
    rescue StandardError => e
      {
        "ok"                => false,
        "recovered"         => false,
        "recovery_required" => true,
        "state"             => "RECOVERY_REQUIRED",
        "code"              => "RECOVERY_EXCEPTION",
        "error"             => e.message
      }
    end

    def self.current_install_stamp(primary_plugins_root)
      parts = []
      ["mapskp.rb", "mapskp/main.rb", "mapskp/payload/rbz_bundle.manifest.json"].each do |rel|
        fp = File.join(primary_plugins_root, rel)
        if File.file?(fp) && !windows_reparse_point?(fp)
          st = File.stat(fp)
          parts << "#{rel}:#{st.size}:#{st.mtime.to_r}"
        else
          parts << "#{rel}:missing"
        end
      end
      Digest::SHA256.hexdigest(parts.join("|"))
    rescue StandardError
      ""
    end

    def self.verify_clean_rbz_reinstall?(primary_plugins_root, pub_hex = PINNED_PUBLISHER_ED25519_PUB_HEX)
      return false if path_has_reparse_ancestor?(primary_plugins_root)
      manifest_fp = File.join(primary_plugins_root, "mapskp", "payload", "rbz_bundle.manifest.json")
      return false unless File.file?(manifest_fp) && !windows_reparse_point?(manifest_fp) && File.size(manifest_fp) <= 262_144
      mdoc = JSON.parse(File.read(manifest_fp, encoding: "UTF-8"), max_nesting: 16)
      ok_sig, _err = verify_publisher_manifest_ed25519(mdoc, pub_hex, expected_schema: "mapskp_rbz_bundle_manifest_v1")
      return false unless ok_sig
      return false unless mdoc["product"].to_s == "mapskp_3d"
      return false unless mdoc["build_number"].to_i >= CURRENT_BUILD_NUMBER

      cat = mdoc["files_catalog"]
      return false unless cat.is_a?(Hash) && !cat.empty?
      cat.each do |rel_path, meta|
        rel_s = rel_path.to_s
        return false unless allowed_plugin_overlay_rel_path?(rel_s)
        return false unless meta.is_a?(Hash)
        fp = File.join(primary_plugins_root, rel_s)
        return false unless File.file?(fp) && !windows_reparse_point?(fp)
        return false unless File.size(fp) == meta["size"].to_i
        return false unless secure_hex_eq?(Digest::SHA256.file(fp).hexdigest, meta["sha256"].to_s)
      end
      true
    rescue StandardError
      false
    end

    def self.clear_stale_tx_state_inside_lock!
      ok_a, auth = read_tx_authority
      next_seq = (ok_a && auth.is_a?(Hash) ? auth["seq"].to_i : 0) + 1
      emb_pyd = File.join(embedded_python_dir, EXPECTED_ABI_PYD_NAME)
      File.delete(emb_pyd) if File.file?(emb_pyd) && !windows_reparse_point?(emb_pyd)
      pend_dir = File.join(updates_root_dir, "pending_activation")
      FileUtils.rm_rf(pend_dir) if Dir.exist?(pend_dir)
      FileUtils.rm_rf(hotpatch_pyd_cache_dir) if Dir.exist?(hotpatch_pyd_cache_dir)
      wm_fp = version_watermark_file
      File.delete(wm_fp) if File.file?(wm_fp) && !windows_reparse_point?(wm_fp)
      j_fp = File.join(updates_root_dir, "tx_journal.json")
      File.delete(j_fp) if File.file?(j_fp) && !windows_reparse_point?(j_fp)
      write_tx_authority!({
        "seq"                     => next_seq,
        "active_tx_id"            => "",
        "pending_tx_id"           => "",
        "recovery_required_tx_id" => "",
        "latched_install_stamp"   => "",
        "updated_at"              => Time.now.to_i
      })
      true
    rescue StandardError
      false
    end

    def self.recovery_required_latched?(primary_plugins_root = nil)
      bdir = File.join(__dir__, "bridge")
      return false if dev_source_protected_bridge?(bdir)
      ok_a, auth = read_tx_authority
      return true unless ok_a && auth.is_a?(Hash)
      return true unless auth["recovery_required_tx_id"].to_s.empty?
      j_fp = File.join(updates_root_dir, "tx_journal.json")
      if File.file?(j_fp) && !windows_reparse_point?(j_fp) && File.size(j_fp) <= MAX_JOURNAL_BYTES
        jdoc = JSON.parse(File.read(j_fp, encoding: "UTF-8"), max_nesting: 16) rescue nil
        return true if jdoc.is_a?(Hash) && jdoc["state"].to_s == "RECOVERY_REQUIRED"
      end
      false
    rescue StandardError
      true
    end

    def self.latch_recovery_required!(j_fp, jdoc_or_nil, auth_or_nil, code_str, errors_arr, primary_plugins_root)
      tx_id = jdoc_or_nil.is_a?(Hash) ? jdoc_or_nil["tx_id"].to_s : "corrupt_tx"
      seq_n = auth_or_nil.is_a?(Hash) ? auth_or_nil["seq"].to_i : 0
      norm_p = primary_plugins_root.to_s.strip.empty? ? "" : File.expand_path(primary_plugins_root.to_s).tr("\\", "/").chomp("/")
      stamp = norm_p.empty? ? "" : current_install_stamp(norm_p)
      write_tx_authority!({
        "seq"                     => seq_n,
        "active_tx_id"            => "",
        "pending_tx_id"           => "",
        "recovery_required_tx_id" => (tx_id.empty? ? "corrupt_tx" : tx_id),
        "latched_install_stamp"   => stamp,
        "updated_at"              => Time.now.to_i
      }) rescue nil
      if jdoc_or_nil.is_a?(Hash)
        jdoc_or_nil["state"] = "RECOVERY_REQUIRED"
        jdoc_or_nil["recovery_code"] = code_str
        jdoc_or_nil["recovery_errors"] = errors_arr
        write_tx_journal!(j_fp, jdoc_or_nil) rescue nil
      end
      {
        "ok"                => false,
        "recovered"         => false,
        "recovery_required" => true,
        "state"             => "RECOVERY_REQUIRED",
        "code"              => code_str,
        "errors"            => errors_arr
      }
    end

    def self.perform_locked_startup_recovery!(primary_plugins_root)
      norm_primary = File.expand_path(primary_plugins_root.to_s).tr("\\", "/").chomp("/")
      j_fp = File.join(updates_root_dir, "tx_journal.json")
      auth_ok, auth = read_tx_authority
      unless auth_ok
        return latch_recovery_required!(j_fp, nil, nil, "TX_AUTHORITY_UNTRUSTED", ["tx_authority.dpapi tampered or unreadable"], norm_primary)
      end

      # Section 20.1: Nếu trước đó đang ở trạng thái RECOVERY_REQUIRED và người dùng đã cài lại gói .RBZ sạch mới qua Extension Manager,
      # chỉ xóa trạng thái khóa sau khi xác minh chữ ký Ed25519 + SHA-256 100% tệp trong .RBZ khớp hoàn toàn!
      if !auth["recovery_required_tx_id"].to_s.empty?
        latched_stamp = auth["latched_install_stamp"].to_s
        cur_stamp = current_install_stamp(norm_primary)
        if !latched_stamp.empty? && !cur_stamp.empty? && cur_stamp != latched_stamp && verify_clean_rbz_reinstall?(norm_primary)
          if clear_stale_tx_state_inside_lock!
            return { "ok" => true, "recovered" => true, "reinstalled_clean_rbz" => true, "state" => "CLEAN_RBZ_REINSTALLED" }
          end
        end
      end

      has_journal = File.exist?(j_fp) || File.symlink?(j_fp)
      unless has_journal
        if !auth["recovery_required_tx_id"].to_s.empty?
          return {
            "ok"                => false,
            "recovered"         => false,
            "recovery_required" => true,
            "state"             => "RECOVERY_REQUIRED",
            "code"              => "RECOVERY_REQUIRED"
          }
        end
        if !auth["active_tx_id"].to_s.empty?
          return latch_recovery_required!(j_fp, nil, auth, "JOURNAL_MISSING_FOR_ACTIVE_TX", ["tx_journal.json missing while active_tx_id set"], norm_primary)
        end
        return { "ok" => true, "recovered" => false, "state" => "CLEAN" }
      end

      if windows_reparse_point?(j_fp) || !File.file?(j_fp) || File.size(j_fp) > MAX_JOURNAL_BYTES
        return latch_recovery_required!(j_fp, nil, auth, "JOURNAL_UNTRUSTED", ["tx_journal.json is reparse point or oversized"], norm_primary)
      end

      jdoc = begin
        JSON.parse(File.read(j_fp, encoding: "UTF-8"), max_nesting: 16)
      rescue StandardError => parse_e
        return latch_recovery_required!(j_fp, nil, auth, "JOURNAL_CORRUPT_JSON", [parse_e.message], norm_primary)
      end

      unless verify_sealed_tx_journal(jdoc)
        return latch_recovery_required!(j_fp, nil, auth, "JOURNAL_SEAL_INVALID", ["tx_journal.json failed DPAPI integrity check"], norm_primary)
      end

      st = jdoc["state"].to_s
      if st == "RECOVERY_REQUIRED" || !auth["recovery_required_tx_id"].to_s.empty?
        return {
          "ok"                => false,
          "recovered"         => false,
          "recovery_required" => true,
          "state"             => "RECOVERY_REQUIRED",
          "code"              => (jdoc["recovery_code"] || "RECOVERY_REQUIRED").to_s,
          "errors"            => (jdoc["recovery_errors"] || jdoc["rollback_errors"] || [])
        }
      end

      if ["COMMITTED", "ROLLED_BACK", "PENDING_RESTART"].include?(st)
        unless auth["active_tx_id"].to_s.empty?
          return latch_recovery_required!(j_fp, jdoc, auth, "JOURNAL_AUTHORITY_STATE_CONFLICT", ["Journal settled while active_tx_id non-empty"], norm_primary)
        end
        return { "ok" => true, "recovered" => false, "state" => st }
      end

      unless ["VERIFIED", "APPLYING", "ROLLING_BACK"].include?(st)
        return latch_recovery_required!(j_fp, jdoc, auth, "JOURNAL_UNKNOWN_STATE", ["Unknown journal state: #{st}"], norm_primary)
      end

      tx_id  = jdoc["tx_id"].to_s
      tx_seq = jdoc["tx_seq"].to_i
      if auth["active_tx_id"].to_s != tx_id || auth["seq"].to_i != tx_seq
        return latch_recovery_required!(j_fp, jdoc, auth, "JOURNAL_REPLAY_DETECTED", ["Replayed or stale tx_journal detected"], norm_primary)
      end

      unless jdoc["primary_root"].to_s == norm_primary
        return latch_recovery_required!(j_fp, jdoc, auth, "JOURNAL_ROOT_MISMATCH", ["Primary root mismatch"], norm_primary)
      end

      safe_tx_dir = tx_id.gsub(/[^A-Za-z0-9_-]/, "")
      bkp_dir = File.join(updates_root_dir, "tx_backups", safe_tx_dir)
      bkp_seal_fp = File.join(bkp_dir, "backup_seal.dpapi")
      if safe_tx_dir.empty? || !Dir.exist?(bkp_dir) || path_has_reparse_ancestor?(bkp_dir, app_state_root) || !File.file?(bkp_seal_fp) || windows_reparse_point?(bkp_seal_fp)
        return latch_recovery_required!(j_fp, jdoc, auth, "JOURNAL_BACKUP_MISSING", ["Verified backup directory or seal missing"], norm_primary)
      end

      bkp_plain = dpapi_unseal_bytes(File.read(bkp_seal_fp, encoding: "UTF-8").strip, "MapSKP_TxBackup_v281")
      unless bkp_plain
        return latch_recovery_required!(j_fp, jdoc, auth, "BACKUP_SEAL_INVALID", ["backup_seal.dpapi failed DPAPI unseal"], norm_primary)
      end
      bkp_meta = JSON.parse(bkp_plain.force_encoding("UTF-8"), max_nesting: 16)
      unless bkp_meta.is_a?(Hash) && bkp_meta["tx_id"].to_s == tx_id && bkp_meta["seq"].to_i == tx_seq && bkp_meta["primary_root"].to_s == norm_primary
        return latch_recovery_required!(j_fp, jdoc, auth, "BACKUP_SEAL_MISMATCH", ["backup_seal.dpapi metadata mismatch"], norm_primary)
      end

      pre_hashes        = bkp_meta["pre_hashes"].is_a?(Hash) ? bkp_meta["pre_hashes"] : {}
      added_files       = bkp_meta["newly_added_files"].is_a?(Array) ? bkp_meta["newly_added_files"] : []
      had_prev_pyd      = bkp_meta["had_prev_pyd"] == true
      prev_pyd_sha      = bkp_meta["prev_pyd_sha"].to_s.downcase
      new_vlt_sha       = bkp_meta["new_vlt_sha"].to_s.downcase
      prev_vlt_sha      = bkp_meta["prev_vlt_sha"].to_s.downcase
      prev_wm_existed   = bkp_meta["prev_wm_existed"] == true
      prev_wm_raw       = bkp_meta["prev_wm_raw"].to_s

      slot_bkp = File.join(bkp_dir, "root_0")
      ok_bkp, err_bkp = validate_strict_plugin_backup_tree(slot_bkp, pre_hashes)
      unless ok_bkp
        return latch_recovery_required!(j_fp, jdoc, auth, err_bkp, ["Backup tree failed strict validation: #{err_bkp}"], norm_primary)
      end

      errors = []
      dest_pyd = File.join(embedded_python_dir, EXPECTED_ABI_PYD_NAME)
      pyd_bkp_fp = File.join(bkp_dir, "pyd_prev", EXPECTED_ABI_PYD_NAME)

      # 1. Khôi phục .pyd
      begin
        if had_prev_pyd
          raise "Missing backup .pyd" unless File.file?(pyd_bkp_fp) && !windows_reparse_point?(pyd_bkp_fp)
          raise "Tampered backup .pyd" unless secure_hex_eq?(Digest::SHA256.file(pyd_bkp_fp).hexdigest, prev_pyd_sha)
          FileUtils.mkdir_p(File.dirname(dest_pyd))
          tmp_p = "#{dest_pyd}.rec_tmp_#{Process.pid}"
          File.binwrite(tmp_p, File.binread(pyd_bkp_fp))
          atomic_replace_file!(tmp_p, dest_pyd)
          raise "Restored .pyd verify failed" unless secure_hex_eq?(Digest::SHA256.file(dest_pyd).hexdigest, prev_pyd_sha)
        elsif File.exist?(dest_pyd)
          File.delete(dest_pyd)
        end
      rescue StandardError => err
        errors << "pyd_recovery:#{err.message}"
      end

      # 2. Dọn cache_slot chưa commit & khôi phục cache cũ nếu có
      begin
        if !new_vlt_sha.empty? && new_vlt_sha != prev_vlt_sha
          uncommitted_slot = File.join(hotpatch_pyd_cache_dir, new_vlt_sha)
          FileUtils.rm_rf(uncommitted_slot) if Dir.exist?(uncommitted_slot) && !windows_reparse_point?(uncommitted_slot)
        end
        prev_cache_bkp = File.join(bkp_dir, "cache_prev")
        if !prev_vlt_sha.empty? && Dir.exist?(prev_cache_bkp)
          prev_slot_dst = File.join(hotpatch_pyd_cache_dir, prev_vlt_sha)
          FileUtils.mkdir_p(prev_slot_dst)
          overlay_directory_files!(prev_cache_bkp, prev_slot_dst)
        end
      rescue StandardError => err
        errors << "cache_recovery:#{err.message}"
      end

      # 3. Khôi phục watermark phiên bản
      begin
        wm_fp = version_watermark_file
        if prev_wm_existed
          FileUtils.mkdir_p(File.dirname(wm_fp))
          File.write(wm_fp, prev_wm_raw, mode: "w:UTF-8")
        elsif File.file?(wm_fp) && !windows_reparse_point?(wm_fp)
          File.delete(wm_fp)
        end
      rescue StandardError => err
        errors << "watermark_recovery:#{err.message}"
      end

      # 4. Xóa tệp mới phát sinh (strict allowlist) & phủ lại slot_bkp
      added_files.each do |rel_p|
        unless allowed_plugin_overlay_rel_path?(rel_p)
          errors << "disallowed_added_file:#{rel_p}"
          next
        end
        fp = File.join(norm_primary, rel_p)
        begin
          File.delete(fp) if File.file?(fp) && !windows_reparse_point?(fp)
        rescue StandardError => err
          errors << "del_added(#{rel_p}):#{err.message}"
        end
      end

      begin
        overlay_plugin_tree_strict!(slot_bkp, norm_primary, pre_hashes)
      rescue StandardError => err
        errors << "plugin_overlay:#{err.message}"
      end

      # 5. Đối chiếu 100% SHA-256 toàn bộ cây plugin & .pyd sau phục hồi
      actual_post = snapshot_plugin_tree_hashes(norm_primary)
      if actual_post != pre_hashes
        errors << "post_recovery_plugin_hashes_mismatch"
      end
      if had_prev_pyd
        if !File.file?(dest_pyd) || !secure_hex_eq?(Digest::SHA256.file(dest_pyd).hexdigest, prev_pyd_sha)
          errors << "post_recovery_pyd_hash_mismatch"
        end
      elsif File.exist?(dest_pyd)
        errors << "post_recovery_unexpected_pyd_present"
      end

      if errors.empty?
        jdoc["state"] = "ROLLED_BACK"
        jdoc["recovery_errors"] = []
        write_tx_journal!(j_fp, jdoc)
        write_tx_authority!({
          "seq"                     => tx_seq,
          "active_tx_id"            => "",
          "pending_tx_id"           => auth["pending_tx_id"].to_s,
          "recovery_required_tx_id" => "",
          "updated_at"              => Time.now.to_i
        })
        { "ok" => true, "recovered" => true, "state" => "ROLLED_BACK", "errors" => [] }
      else
        latch_recovery_required!(j_fp, jdoc, auth, "RECOVERY_VERIFICATION_FAILED", errors, norm_primary)
      end
    end

    def self.pending_activation_dir
      File.join(updates_root_dir, "pending_activation")
    end

    def self.pending_restart_info
      seal_fp = File.join(pending_activation_dir, "pending_seal.dpapi")
      zip_fp  = File.join(pending_activation_dir, "pending_hotpatch.zip")
      return { "pending_restart" => false, "target_version" => "" } unless File.file?(seal_fp) && File.file?(zip_fp)
      return { "pending_restart" => false, "target_version" => "" } if windows_reparse_point?(seal_fp) || windows_reparse_point?(zip_fp)
      plain = dpapi_unseal_bytes(File.read(seal_fp, encoding: "UTF-8").strip, "MapSKP_PendingAct_v281")
      return { "pending_restart" => false, "target_version" => "" } unless plain
      pdoc = JSON.parse(plain.force_encoding("UTF-8"), max_nesting: 16)
      return { "pending_restart" => false, "target_version" => "" } unless pdoc.is_a?(Hash)
      { "pending_restart" => true, "target_version" => pdoc["latest_version"].to_s }
    rescue StandardError
      { "pending_restart" => false, "target_version" => "" }
    end

    def self.verify_installed_files_match_signed_catalog!(primary_plugins_root, dest_pyd, cache_slot, ch_doc)
      signed_cat = ch_doc["files_catalog"]
      raise "Signed catalog missing" unless signed_cat.is_a?(Hash) && !signed_cat.empty?
      signed_pyd_rel  = ch_doc["pyd_rel_path"].to_s.strip
      signed_pyd_sha  = ch_doc["pyd_sha256"].to_s.strip.downcase
      signed_pyd_size = ch_doc["pyd_size_bytes"].to_i

      raise "Installed .pyd missing" unless File.file?(dest_pyd) && !windows_reparse_point?(dest_pyd)
      raise "Installed .pyd size mismatch" unless File.size(dest_pyd) == signed_pyd_size
      raise "Installed .pyd SHA256 mismatch" unless secure_hex_eq?(Digest::SHA256.file(dest_pyd).hexdigest, signed_pyd_sha)

      cached_pyd = File.join(cache_slot, EXPECTED_ABI_PYD_NAME)
      raise "Cached .pyd missing" unless File.file?(cached_pyd) && !windows_reparse_point?(cached_pyd)
      raise "Cached .pyd size mismatch" unless File.size(cached_pyd) == signed_pyd_size
      raise "Cached .pyd SHA256 mismatch" unless secure_hex_eq?(Digest::SHA256.file(cached_pyd).hexdigest, signed_pyd_sha)

      signed_cat.each do |arc_rel, meta|
        next if arc_rel == signed_pyd_rel
        next unless arc_rel.start_with?("plugin_root/")
        plug_rel = arc_rel.sub(/\Aplugin_root\//, "")
        fp = File.join(primary_plugins_root, plug_rel)
        raise "Post-verify missing file: #{plug_rel}" unless File.file?(fp) && !windows_reparse_point?(fp)
        raise "Post-verify size mismatch: #{plug_rel}" unless File.size(fp) == meta["size"].to_i
        raise "Post-verify SHA256 mismatch: #{plug_rel}" unless secure_hex_eq?(Digest::SHA256.file(fp).hexdigest, meta["sha256"].to_s)
      end
      true
    end

    # Section 20 & #02: Kích hoạt gói PENDING_RESTART ngay đầu phiên mới trước khi nạp Python (0% trộn phiên bản)
    def self.activate_pending_update_if_ready!(primary_plugins_root, bridge_dir, pub_hex = PINNED_PUBLISHER_ED25519_PUB_HEX)
      norm_primary = File.expand_path(primary_plugins_root.to_s).tr("\\", "/").chomp("/")
      p_dir   = pending_activation_dir
      seal_fp = File.join(p_dir, "pending_seal.dpapi")
      zip_fp  = File.join(p_dir, "pending_hotpatch.zip")
      return { "ok" => true, "activated" => false } unless File.exist?(seal_fp) || File.exist?(zip_fp)

      lock_fp = File.join(updates_root_dir, ".update_tx.lock")
      res = with_file_lock(lock_fp, 8.0) do
        next { "ok" => true, "activated" => false } unless File.exist?(seal_fp) || File.exist?(zip_fp)
        j_fp = File.join(updates_root_dir, "tx_journal.json")
        auth_ok, auth = read_tx_authority
        unless auth_ok
          next latch_recovery_required!(j_fp, nil, nil, "PENDING_AUTH_UNTRUSTED", ["tx_authority.dpapi unreadable during pending activation"], norm_primary)
        end

        if !File.file?(seal_fp) || !File.file?(zip_fp) || windows_reparse_point?(seal_fp) || windows_reparse_point?(zip_fp) || File.size(zip_fp) > MAX_HOTPATCH_ZIP_BYTES
          next latch_recovery_required!(j_fp, nil, auth, "PENDING_FILES_TAMPERED", ["Pending activation files missing or unsafe"], norm_primary)
        end

        plain = dpapi_unseal_bytes(File.read(seal_fp, encoding: "UTF-8").strip, "MapSKP_PendingAct_v281")
        unless plain
          next latch_recovery_required!(j_fp, nil, auth, "PENDING_SEAL_INVALID", ["pending_seal.dpapi failed DPAPI unseal"], norm_primary)
        end
        pdoc = JSON.parse(plain.force_encoding("UTF-8"), max_nesting: 20)
        unless pdoc.is_a?(Hash) && pdoc["tx_id"].to_s == auth["pending_tx_id"].to_s && pdoc["primary_root"].to_s == primary_plugins_root
          next latch_recovery_required!(j_fp, nil, auth, "PENDING_TX_MISMATCH", ["Pending tx_id or root mismatch"], norm_primary)
        end

        signed_manifest = pdoc["signed_manifest"]
        sig_ok, sig_err = verify_publisher_manifest_ed25519(signed_manifest, pub_hex, expected_schema: "mapskp_update_manifest_v1")
        unless sig_ok
          next latch_recovery_required!(j_fp, nil, auth, sig_err, ["Pending signed_manifest invalid"], norm_primary)
        end

        ch_key = pdoc["channel"].to_s
        ch_doc = signed_manifest["channels"].is_a?(Hash) ? signed_manifest["channels"][ch_key] : nil
        zip_bytes = File.binread(zip_fp)
        mem_entries, z_err = parse_and_verify_hotpatch_zip_bytes(zip_bytes, ch_doc)
        unless mem_entries
          next latch_recovery_required!(j_fp, nil, auth, z_err, ["Pending hotpatch zip verification failed"], norm_primary)
        end

        next { "ok" => false, "recovery_required" => true, "code" => "RUNTIME_UNVERIFIED" } unless try_unpack_offline_bundle!(bridge_dir, pub_hex: pub_hex)

        dest_pyd        = File.join(embedded_python_dir, EXPECTED_ABI_PYD_NAME)
        pyd_bytes       = mem_entries[ch_doc["pyd_rel_path"].to_s]
        pyd_new_sha     = ch_doc["pyd_sha256"].to_s.downcase
        vlt_new_sha     = ch_doc["vlt_sha256"].to_s.downcase
        latest_ver      = pdoc["latest_version"].to_s
        had_prev_pyd    = File.file?(dest_pyd)
        prev_pyd_sha    = had_prev_pyd ? Digest::SHA256.file(dest_pyd).hexdigest.downcase : ""
        cur_vlt_fp      = File.join(bridge_dir.to_s, "core_ip.vlt")
        prev_vlt_sha    = File.file?(cur_vlt_fp) ? Digest::SHA256.file(cur_vlt_fp).hexdigest.downcase : ""
        prev_wm_existed = File.file?(version_watermark_file)
        prev_wm_raw     = prev_wm_existed ? File.read(version_watermark_file, encoding: "UTF-8") : ""

        pre_hashes   = snapshot_plugin_tree_hashes(primary_plugins_root)
        new_plug_rel = mem_entries.keys.select { |k| k.start_with?("plugin_root/") }.map { |k| k.sub(/\Aplugin_root\//, "") }
        newly_added  = new_plug_rel - pre_hashes.keys

        act_seq = auth["seq"].to_i + 1
        tx_id   = "tx_act_#{Time.now.to_i}_#{SecureRandom.hex(4)}"
        bkp_dir = File.join(updates_root_dir, "tx_backups", tx_id)
        pyd_bkp = File.join(bkp_dir, "pyd_prev", EXPECTED_ABI_PYD_NAME)
        cache_slot = File.join(hotpatch_pyd_cache_dir, vlt_new_sha)

        FileUtils.rm_rf(bkp_dir)
        FileUtils.mkdir_p(File.join(bkp_dir, "pyd_prev"))
        FileUtils.cp(dest_pyd, pyd_bkp) if had_prev_pyd
        slot_bkp = File.join(bkp_dir, "root_0")
        FileUtils.mkdir_p(File.join(slot_bkp, "mapskp"))
        FileUtils.cp(File.join(primary_plugins_root, "mapskp.rb"), File.join(slot_bkp, "mapskp.rb")) if File.file?(File.join(primary_plugins_root, "mapskp.rb"))
        overlay_directory_files!(File.join(primary_plugins_root, "mapskp"), File.join(slot_bkp, "mapskp")) if Dir.exist?(File.join(primary_plugins_root, "mapskp"))
        prev_cache_dir = File.join(hotpatch_pyd_cache_dir, prev_vlt_sha)
        if !prev_vlt_sha.empty? && Dir.exist?(prev_cache_dir)
          FileUtils.mkdir_p(File.join(bkp_dir, "cache_prev"))
          overlay_directory_files!(prev_cache_dir, File.join(bkp_dir, "cache_prev"))
        end

        bkp_seal = dpapi_seal_bytes(canonical_json_str({
          "tx_id" => tx_id, "seq" => act_seq, "primary_root" => primary_plugins_root,
          "pre_hashes" => pre_hashes, "newly_added_files" => newly_added,
          "had_prev_pyd" => had_prev_pyd, "prev_pyd_sha" => prev_pyd_sha,
          "new_vlt_sha" => vlt_new_sha, "prev_vlt_sha" => prev_vlt_sha,
          "prev_wm_existed" => prev_wm_existed, "prev_wm_raw" => prev_wm_raw
        }), "MapSKP_TxBackup_v281")
        File.write(File.join(bkp_dir, "backup_seal.dpapi"), bkp_seal, mode: "w:UTF-8")

        # Kiểm tra thử xem cửa sổ SketchUp khác đã đóng và nhả khóa .pyd chưa
        can_replace_pyd = false
        begin
          tmp_pyd = "#{dest_pyd}.act_tmp_#{Process.pid}"
          File.binwrite(tmp_pyd, pyd_bytes)
          atomic_replace_file!(tmp_pyd, dest_pyd)
          can_replace_pyd = secure_hex_eq?(Digest::SHA256.file(dest_pyd).hexdigest, pyd_new_sha)
        rescue StandardError
          File.delete("#{dest_pyd}.act_tmp_#{Process.pid}") rescue nil
          can_replace_pyd = false
        end

        unless can_replace_pyd
          FileUtils.rm_rf(bkp_dir) rescue nil
          next { "ok" => true, "activated" => false, "still_locked" => true, "pending_restart" => true }
        end

        jstate = {
          "tx_id" => tx_id, "tx_seq" => act_seq, "owner_pid" => Process.pid,
          "state" => "APPLYING", "latest_version" => latest_ver, "primary_root" => primary_plugins_root,
          "started_at" => Time.now.to_i
        }
        write_tx_authority!({
          "seq" => act_seq, "active_tx_id" => tx_id, "pending_tx_id" => auth["pending_tx_id"].to_s,
          "recovery_required_tx_id" => "", "updated_at" => Time.now.to_i
        })
        write_tx_journal!(j_fp, jstate)

        begin
          FileUtils.mkdir_p(cache_slot)
          File.binwrite(File.join(cache_slot, EXPECTED_ABI_PYD_NAME), pyd_bytes)
          File.write(File.join(cache_slot, "cache_manifest.json"), JSON.pretty_generate({
            "vlt_sha256" => vlt_new_sha, "pyd_sha256" => pyd_new_sha,
            "channel" => ch_key, "signed_manifest" => signed_manifest
          }), mode: "w:UTF-8")
          write_verified_plugin_entries_from_memory!(mem_entries, primary_plugins_root)
          verify_installed_files_match_signed_catalog!(primary_plugins_root, dest_pyd, cache_slot, ch_doc)

          jstate["state"] = "COMMITTED"
          write_tx_journal!(j_fp, jstate)
          write_tx_authority!({
            "seq" => act_seq, "active_tx_id" => "", "pending_tx_id" => "",
            "recovery_required_tx_id" => "", "updated_at" => Time.now.to_i
          })
          write_committed_version_watermark!(latest_ver)
          FileUtils.rm_rf(p_dir) rescue nil
          { "ok" => true, "activated" => true, "latest_version" => latest_ver }
        rescue StandardError
          perform_locked_startup_recovery!(primary_plugins_root)
        end
      end
      res || { "ok" => true, "activated" => false }
    rescue StandardError => e
      { "ok" => false, "recovery_required" => true, "code" => "PENDING_ACTIVATE_ERROR", "error" => e.message }
    end

    # #02, #03, #04, #05, #06 & Section 20: Giao dịch cập nhật nguyên tử từ bytes ZIP đã ký trong RAM
    def self.apply_staged_hotpatch!(bridge_dir, staged_dir_or_nil, parent_pid = 0, opts = {})
      if dev_source_protected_bridge?(bridge_dir)
        return {
          "ok"                    => false,
          "dev_protected_dry_run" => true,
          "code"                  => "DEV_WORKSPACE_DRY_RUN",
          "message"               => "🛡️ Đã bảo vệ mã nguồn .py gốc trên máy phát triển — bỏ qua bước ghi đè thư mục Plugins."
        }
      end

      active_tok = opts[:ipc_token] || @ipc_token
      pub_hex    = opts[:pub_hex] || PINNED_PUBLISHER_ED25519_PUB_HEX
      upd_job_id = opts[:update_job_id].to_s.strip
      job_fp     = nil
      job_doc    = nil

      staged_dir = staged_dir_or_nil.to_s.strip
      if !upd_job_id.empty?
        resolved_dir, j_err, job_fp, job_doc = resolve_staged_dir_from_job_id(upd_job_id, active_tok)
        unless resolved_dir
          return {
            "ok"    => false,
            "code"  => j_err,
            "error" => "Phiên cập nhật không hợp lệ hoặc đã được xử lý (#{j_err})."
          }
        end
        staged_dir = resolved_dir
      end

      unless safe_staged_dir?(staged_dir)
        return {
          "ok"    => false,
          "code"  => "STAGED_PATH_OUTSIDE_MANAGED_UPDATES_DIR",
          "error" => "Đường dẫn gói cập nhật nằm ngoài vùng bộ đệm an toàn của MapSKP — đã từ chối thực thi!"
        }
      end

      lock_fp = File.join(updates_root_dir, ".update_tx.lock")
      tx_result = with_file_lock(lock_fp, 10.0) do
        auth_ok, auth = read_tx_authority
        unless auth_ok && auth["recovery_required_tx_id"].to_s.empty?
          next {
            "ok"    => false,
            "code"  => "RECOVERY_REQUIRED",
            "error" => "Hệ thống đang chờ khôi phục bản cài gốc (.RBZ) trước khi áp dụng bản vá mới."
          }
        end

        s_dir = File.expand_path(staged_dir.to_s).tr("\\", "/").chomp("/")
        ready_json = File.join(s_dir, "staged_ready.json")
        if !File.file?(ready_json) || windows_reparse_point?(ready_json) || File.size(ready_json) > 1_048_576
          next {
            "ok"    => false,
            "code"  => "STAGED_PACKAGE_INCOMPLETE",
            "error" => "Không tìm thấy đủ thành phần cốt lõi trong bộ đệm cập nhật."
          }
        end

        ready_meta = JSON.parse(File.read(ready_json, encoding: "UTF-8"), max_nesting: 20)
        ver_ok, ver_err, mem_entries, zip_bytes, ch_doc = verify_staged_files_integrity!(s_dir, ready_meta, active_tok, pub_hex)
        unless ver_ok && mem_entries && zip_bytes && ch_doc
          next {
            "ok"    => false,
            "code"  => ver_err,
            "error" => "Kiểm định chữ ký số Ed25519 / SHA-256 / HMAC không khớp (#{ver_err}) — đã chặn đứng trước khi ghi!"
          }
        end

        primary_plugins_root = File.expand_path("../..", bridge_dir.to_s).tr("\\", "/").chomp("/")
        if !valid_plugins_root_contract?(primary_plugins_root) || path_has_reparse_ancestor?(primary_plugins_root)
          next {
            "ok"    => false,
            "code"  => "TARGET_PLUGINS_REPARSE_UNSAFE",
            "error" => "Thư mục Plugins đích không hợp lệ hoặc chứa liên kết chuyển hướng không an toàn."
          }
        end

        cur_ver = read_plugin_version(primary_plugins_root)
        latest_ver = ready_meta["latest_version"].to_s.strip
        wm_ver = read_committed_version_watermark(cur_ver)
        if (parse_semver_array(latest_ver) <=> wm_ver) <= 0
          next {
            "ok"    => false,
            "code"  => "UPDATE_DOWNGRADE_OR_REPLAY_BLOCKED",
            "error" => "Phiên bản cập nhật (v#{latest_ver}) không mới hơn phiên bản đã kích hoạt."
          }
        end

        cur_mode = read_plugin_dist_mode(primary_plugins_root)
        prof_bytes = mem_entries["plugin_root/mapskp/distribution_profile.json"]
        expected_mode = prof_bytes ? (JSON.parse(prof_bytes.dup.force_encoding("UTF-8"))["distribution_mode"].to_s.strip rescue "") : ""
        if !cur_mode.empty? && !expected_mode.empty? && cur_mode != expected_mode
          next {
            "ok"    => false,
            "code"  => "UPDATE_CHANNEL_MISMATCH",
            "error" => "Kênh phân phối của gói cập nhật không khớp với phiên bản đang cài."
          }
        end

        unless try_unpack_offline_bundle!(bridge_dir, pub_hex: pub_hex)
          next {
            "ok"    => false,
            "code"  => "RUNTIME_BUNDLE_INTACT_CHECK_FAILED",
            "error" => "Không thể xác minh bộ runtime nền trước khi cập nhật."
          }
        end

        emb_dir       = embedded_python_dir
        dest_pyd      = File.join(emb_dir, EXPECTED_ABI_PYD_NAME)
        pyd_rel_key   = ch_doc["pyd_rel_path"].to_s.strip
        pyd_bytes     = mem_entries[pyd_rel_key]
        vlt_sha       = ch_doc["vlt_sha256"].to_s.strip.downcase
        pyd_new_sha   = ch_doc["pyd_sha256"].to_s.strip.downcase
        pyd_new_size  = ch_doc["pyd_size_bytes"].to_i

        roots           = discover_compatible_plugin_roots(primary_plugins_root, expected_mode)
        tx_seq          = auth["seq"].to_i + 1
        tx_id           = "tx_#{Time.now.to_i}_#{SecureRandom.hex(4)}"
        backup_dir      = File.join(updates_root_dir, "tx_backups", tx_id)
        journal_path    = File.join(updates_root_dir, "tx_journal.json")
        pyd_backup_file = File.join(backup_dir, "pyd_prev", EXPECTED_ABI_PYD_NAME)
        had_prev_pyd    = File.file?(dest_pyd)
        prev_pyd_sha    = had_prev_pyd ? Digest::SHA256.file(dest_pyd).hexdigest.downcase : ""
        cur_vlt_fp      = File.join(bridge_dir.to_s, "core_ip.vlt")
        prev_vlt_sha    = File.file?(cur_vlt_fp) ? Digest::SHA256.file(cur_vlt_fp).hexdigest.downcase : ""
        prev_wm_existed = File.file?(version_watermark_file)
        prev_wm_raw     = prev_wm_existed ? File.read(version_watermark_file, encoding: "UTF-8") : ""

        pre_hashes = snapshot_plugin_tree_hashes(primary_plugins_root)
        new_plug_files = mem_entries.keys.select { |k| k.start_with?("plugin_root/") }.map { |k| k.sub(/\Aplugin_root\//, "") }
        newly_added_files = new_plug_files - pre_hashes.keys

        # Bước 1: Tạo backup đầy đủ + niêm phong DPAPI backup_seal.dpapi TRƯỚC KHI tắt Bridge hoặc ghi tệp
        begin
          FileUtils.rm_rf(backup_dir)
          FileUtils.mkdir_p(File.join(backup_dir, "pyd_prev"))
          if had_prev_pyd
            FileUtils.cp(dest_pyd, pyd_backup_file)
            raise "Backup .pyd hash mismatch" unless secure_hex_eq?(Digest::SHA256.file(pyd_backup_file).hexdigest, prev_pyd_sha)
          end
          prev_cache_dir = File.join(hotpatch_pyd_cache_dir, prev_vlt_sha)
          if !prev_vlt_sha.empty? && Dir.exist?(prev_cache_dir)
            FileUtils.mkdir_p(File.join(backup_dir, "cache_prev"))
            overlay_directory_files!(prev_cache_dir, File.join(backup_dir, "cache_prev"))
          end
          roots.each_with_index do |r_path, idx|
            slot_bkp = File.join(backup_dir, "root_#{idx}")
            FileUtils.mkdir_p(File.join(slot_bkp, "mapskp"))
            rb_entry = File.join(r_path, "mapskp.rb")
            FileUtils.cp(rb_entry, File.join(slot_bkp, "mapskp.rb")) if File.file?(rb_entry)
            src_mapskp_dir = File.join(r_path, "mapskp")
            overlay_directory_files!(src_mapskp_dir, File.join(slot_bkp, "mapskp")) if Dir.exist?(src_mapskp_dir)
            if idx == 0
              ok_bkp, err_bkp = validate_strict_plugin_backup_tree(slot_bkp, pre_hashes)
              raise "Backup validation failed: #{err_bkp}" unless ok_bkp
            end
          end
          bkp_seal = dpapi_seal_bytes(canonical_json_str({
            "tx_id"             => tx_id,
            "seq"               => tx_seq,
            "primary_root"      => primary_plugins_root,
            "pre_hashes"        => pre_hashes,
            "newly_added_files" => newly_added_files,
            "had_prev_pyd"      => had_prev_pyd,
            "prev_pyd_sha"      => prev_pyd_sha,
            "new_vlt_sha"       => vlt_sha,
            "prev_vlt_sha"      => prev_vlt_sha,
            "prev_wm_existed"   => prev_wm_existed,
            "prev_wm_raw"       => prev_wm_raw
          }), "MapSKP_TxBackup_v281")
          raise "Backup DPAPI seal failed" unless bkp_seal
          File.write(File.join(backup_dir, "backup_seal.dpapi"), bkp_seal, mode: "w:UTF-8")
        rescue StandardError => bkp_err
          FileUtils.rm_rf(backup_dir) rescue nil
          next {
            "ok"    => false,
            "code"  => "BACKUP_PRECHECK_FAILED",
            "error" => "Không thể tạo và xác minh bản sao lưu an toàn trước khi cập nhật (#{bkp_err.message})!"
          }
        end

        @in_active_update_tx_id = tx_id
        begin
          journal_state = {
            "tx_id"             => tx_id,
            "tx_seq"            => tx_seq,
            "owner_pid"         => Process.pid,
            "state"             => "VERIFIED",
            "latest_version"    => latest_ver,
            "primary_root"      => primary_plugins_root,
            "had_prev_pyd"      => had_prev_pyd,
            "prev_pyd_sha"      => prev_pyd_sha,
            "pre_hashes"        => pre_hashes,
            "newly_added_files" => newly_added_files,
            "started_at"        => Time.now.to_i
          }
          write_tx_authority!({
            "seq"                     => tx_seq,
            "active_tx_id"            => tx_id,
            "pending_tx_id"           => auth["pending_tx_id"].to_s,
            "recovery_required_tx_id" => "",
            "updated_at"              => Time.now.to_i
          })
          write_tx_journal!(journal_path, journal_state)

          force_shutdown_bridge_for_update!

          pyd_locked_by_other_su = false
          cache_slot = File.join(hotpatch_pyd_cache_dir, vlt_sha)
          new_st = { "alive" => true }

          begin
            journal_state["state"] = "APPLYING"
            write_tx_journal!(journal_path, journal_state)

            copied_pyd = false
            10.times do
              begin
                tmp_pyd = "#{dest_pyd}.upd_tmp_#{Process.pid}"
                File.binwrite(tmp_pyd, pyd_bytes)
                atomic_replace_file!(tmp_pyd, dest_pyd)
                copied_pyd = (File.size(dest_pyd) == pyd_new_size) && secure_hex_eq?(Digest::SHA256.file(dest_pyd).hexdigest, pyd_new_sha)
                break if copied_pyd
              rescue StandardError
                File.delete("#{dest_pyd}.upd_tmp_#{Process.pid}") rescue nil
                sleep(0.1)
              end
            end

            unless copied_pyd
              if opts[:strict_fail_on_locked_pyd]
                raise "Tiến trình nền chưa nhả tệp nhân bảo mật (.pyd)"
              end
              pyd_locked_by_other_su = true
            end

            # Section 20 & #02.4: Nếu .pyd đang bị giữ bởi cửa sổ SketchUp thứ 2 -> TUYỆT ĐỐI KHÔNG ghi đè mapskp/ hay nâng watermark!
            if pyd_locked_by_other_su
              p_dir = pending_activation_dir
              FileUtils.rm_rf(p_dir)
              FileUtils.mkdir_p(p_dir)
              File.binwrite(File.join(p_dir, "pending_hotpatch.zip"), zip_bytes)
              p_seal = dpapi_seal_bytes(canonical_json_str({
                "tx_id"           => tx_id,
                "latest_version"  => latest_ver,
                "channel"         => ready_meta["channel"].to_s,
                "primary_root"    => primary_plugins_root,
                "signed_manifest" => ready_meta["signed_manifest"]
              }), "MapSKP_PendingAct_v281")
              raise "Pending DPAPI seal failed" unless p_seal
              File.write(File.join(p_dir, "pending_seal.dpapi"), p_seal, mode: "w:UTF-8")

              journal_state["state"] = "PENDING_RESTART"
              write_tx_journal!(journal_path, journal_state)
              write_tx_authority!({
                "seq"                     => tx_seq,
                "active_tx_id"            => "",
                "pending_tx_id"           => tx_id,
                "recovery_required_tx_id" => "",
                "updated_at"              => Time.now.to_i
              })
              FileUtils.rm_rf(backup_dir) rescue nil
              old_bridge = parent_pid.to_i > 0 ? ensure_bridge_running!(bridge_dir, parent_pid, in_update_tx: true) : { "alive" => true }
              if job_fp && job_doc
                job_doc["consumed"] = true
                File.write(job_fp, JSON.pretty_generate(job_doc), mode: "w:UTF-8") rescue nil
              end
              next {
                "ok"                  => true,
                "status"              => "PENDING_RESTART",
                "activated"           => false,
                "pending_restart"     => true,
                "latest_version"      => latest_ver,
                "updated_roots_count" => 0,
                "bridge"              => old_bridge,
                "message"             => "Đã xác thực xong bản v#{latest_ver}. Đang có cửa sổ SketchUp khác mở — vui lòng đóng hết SketchUp rồi mở lại để kích hoạt đồng bộ!"
              }
            end

            FileUtils.mkdir_p(cache_slot)
            File.binwrite(File.join(cache_slot, EXPECTED_ABI_PYD_NAME), pyd_bytes)
            cache_manifest = {
              "vlt_sha256"      => vlt_sha,
              "pyd_sha256"      => pyd_new_sha,
              "channel"         => ready_meta["channel"].to_s,
              "signed_manifest" => ready_meta["signed_manifest"]
            }
            File.write(File.join(cache_slot, "cache_manifest.json"), JSON.pretty_generate(cache_manifest), mode: "w:UTF-8")

            roots.each do |target_plugins_root|
              write_verified_plugin_entries_from_memory!(mem_entries, target_plugins_root)
            end

            # Kiểm tra toàn vẹn lần 1 trước khi chạy healthcheck Bridge
            verify_installed_files_match_signed_catalog!(primary_plugins_root, dest_pyd, cache_slot, ch_doc)

            # #02.1: Chạy healthcheck với in_update_tx: true để KHÔNG tự gọi startup recovery đè lên giao dịch đang mở!
            if parent_pid.to_i > 0
              new_st = ensure_bridge_running!(bridge_dir, parent_pid, in_update_tx: true)
              unless new_st["alive"]
                raise "Bridge healthcheck failed after update (#{new_st['error_code'] || new_st['runtime_source']})"
              end
            end

            # #02.3: Kiểm tra lại toàn bộ tệp SAU healthcheck, TRƯỚC KHI ghi COMMITTED và version watermark!
            verify_installed_files_match_signed_catalog!(primary_plugins_root, dest_pyd, cache_slot, ch_doc)
          rescue StandardError => e
            journal_state["state"] = "ROLLING_BACK"
            write_tx_journal!(journal_path, journal_state) rescue nil
            force_shutdown_bridge_for_update! rescue nil
            rollback_errors = []

            # 1. Xóa cache_slot chưa commit & phục hồi cache cũ
            begin
              FileUtils.rm_rf(cache_slot) if Dir.exist?(cache_slot) && vlt_sha != prev_vlt_sha
              prev_cache_bkp = File.join(backup_dir, "cache_prev")
              if !prev_vlt_sha.empty? && Dir.exist?(prev_cache_bkp)
                prev_slot_dst = File.join(hotpatch_pyd_cache_dir, prev_vlt_sha)
                FileUtils.mkdir_p(prev_slot_dst)
                overlay_directory_files!(prev_cache_bkp, prev_slot_dst)
              end
            rescue StandardError => rb_err
              rollback_errors << "cache_cleanup:#{rb_err.message}"
            end

            # 2. Khôi phục .pyd
            begin
              if had_prev_pyd
                raise "Missing backup .pyd" unless File.file?(pyd_backup_file)
                FileUtils.cp(pyd_backup_file, dest_pyd)
                unless secure_hex_eq?(Digest::SHA256.file(dest_pyd).hexdigest, prev_pyd_sha)
                  raise "Restored .pyd SHA256 mismatch"
                end
              elsif File.file?(dest_pyd)
                File.delete(dest_pyd)
              end
            rescue StandardError => rb_err
              rollback_errors << "pyd_restore:#{rb_err.message}"
            end

            # 3. Xóa tệp mới phát sinh & khôi phục strict allowlist từ backup
            roots.each_with_index do |r_path, idx|
              newly_added_files.each do |new_rel|
                next unless allowed_plugin_overlay_rel_path?(new_rel)
                added_fp = File.join(r_path, new_rel)
                begin
                  File.delete(added_fp) if File.file?(added_fp) && !windows_reparse_point?(added_fp)
                rescue StandardError => rb_err
                  rollback_errors << "del_new(#{new_rel}):#{rb_err.message}"
                end
              end
              begin
                slot_bkp = File.join(backup_dir, "root_#{idx}")
                raise "Missing root backup #{idx}" unless Dir.exist?(slot_bkp)
                overlay_plugin_tree_strict!(slot_bkp, r_path, idx == 0 ? pre_hashes : nil)
              rescue StandardError => rb_err
                rollback_errors << "root_restore(#{idx}):#{rb_err.message}"
              end
            end

            # 4. Đối chiếu 100% SHA-256 sau Rollback
            restored_hashes = snapshot_plugin_tree_hashes(primary_plugins_root)
            rollback_errors << "post_rollback_tree_hash_mismatch" if restored_hashes != pre_hashes
            if had_prev_pyd
              rollback_errors << "post_rollback_pyd_hash_mismatch" if !File.file?(dest_pyd) || !secure_hex_eq?(Digest::SHA256.file(dest_pyd).hexdigest, prev_pyd_sha)
            elsif File.exist?(dest_pyd)
              rollback_errors << "post_rollback_unexpected_pyd"
            end

            if rollback_errors.empty?
              journal_state["state"] = "ROLLED_BACK"
              write_tx_journal!(journal_path, journal_state) rescue nil
              write_tx_authority!({
                "seq"                     => tx_seq,
                "active_tx_id"            => "",
                "pending_tx_id"           => auth["pending_tx_id"].to_s,
                "recovery_required_tx_id" => "",
                "updated_at"              => Time.now.to_i
              }) rescue nil
              ensure_bridge_running!(bridge_dir, parent_pid, in_update_tx: true) if parent_pid.to_i > 0
              next {
                "ok"    => false,
                "code"  => "UPDATE_APPLY_ROLLED_BACK",
                "error" => "Lỗi ghi tệp cập nhật (đã tự động khôi phục và xác minh nguyên trạng 100% bản cũ): #{e.message}"
              }
            else
              latch_recovery_required!(journal_path, journal_state, auth.merge("seq" => tx_seq), "ROLLBACK_FAILED_RECOVERY_REQUIRED", rollback_errors, primary_plugins_root)
              next {
                "ok"                => false,
                "recovery_required" => true,
                "code"              => "ROLLBACK_FAILED_RECOVERY_REQUIRED",
                "rollback_errors"   => rollback_errors,
                "error"             => "Cập nhật thất bại và không thể tự khôi phục hoàn toàn (#{rollback_errors.first}). Vui lòng cài lại tệp .RBZ chính thức!"
              }
            end
          end

          journal_state["state"] = "COMMITTED"
          write_tx_journal!(journal_path, journal_state)
          write_tx_authority!({
            "seq"                     => tx_seq,
            "active_tx_id"            => "",
            "pending_tx_id"           => "",
            "recovery_required_tx_id" => "",
            "updated_at"              => Time.now.to_i
          })
          write_committed_version_watermark!(latest_ver)
          FileUtils.rm_rf(pending_activation_dir) rescue nil
          if job_fp && job_doc
            job_doc["consumed"] = true
            File.write(job_fp, JSON.pretty_generate(job_doc), mode: "w:UTF-8") rescue nil
          end

          {
            "ok"                  => true,
            "status"              => "COMMITTED",
            "activated"           => true,
            "pending_restart"     => false,
            "latest_version"      => latest_ver,
            "updated_roots_count" => roots.length,
            "bridge"              => new_st
          }
        ensure
          @in_active_update_tx_id = nil
        end
      end

      tx_result || {
        "ok"    => false,
        "code"  => "UPDATE_LOCK_BUSY",
        "error" => "Đang có một tiến trình cập nhật MapSKP khác chạy song song — vui lòng thử lại sau giây lát."
      }
    end

    def self.port_free?(port)
      srv = TCPServer.new("127.0.0.1", port)
      srv.close
      true
    rescue StandardError
      false
    end

    def self.resolve_bridge_port
      if @spawned_by_self && @spawned_pid.to_i > 0 && @ipc_token.to_s.bytesize >= 32
        if probe_mapskp_bridge?(@active_port, @ipc_token, @spawned_pid)
          return [@active_port, true]
        else
          @spawned_by_self = false
          @spawned_pid = 0
          @ipc_token = ""
        end
      end

      PORT_RANGE.each do |p|
        if port_free?(p)
          @active_port = p
          return [p, false]
        end
      end

      begin
        srv = TCPServer.new("127.0.0.1", 0)
        ephem = srv.addr[1].to_i
        srv.close
        if ephem >= 1024 && ephem <= 65535
          @active_port = ephem
          return [ephem, false]
        end
      rescue StandardError
        nil
      end

      [@active_port, false]
    end

    def self.ensure_bridge_running!(bridge_dir, parent_pid = 0, in_update_tx: false, su_exe_dir_override: nil)
      cleanup_legacy_ipc_token_file!
      su_dir = su_exe_dir_override.nil? ? sketchup_exe_dir : su_exe_dir_override.to_s
      primary_plugins_root = File.expand_path("../..", bridge_dir.to_s).tr("\\", "/").chomp("/")

      if !in_update_tx && !dev_source_protected_bridge?(bridge_dir)
        rec_res = recover_interrupted_update_if_needed!(primary_plugins_root)
        if rec_res["recovery_required"] || rec_res["ok"] == false
          @spawned_by_self = false
          @spawned_pid = 0
          @ipc_token = ""
          return {
            "alive"             => false,
            "recovery_required" => true,
            "port"              => 0,
            "pid"               => 0,
            "ipc_token"         => "",
            "error_code"        => (rec_res["code"] || "RECOVERY_REQUIRED").to_s,
            "error"             => "Bản cập nhật trước bị gián đoạn và chưa thể tự khôi phục đồng bộ (#{rec_res['code'] || 'RECOVERY_REQUIRED'}). Vui lòng cài lại tệp .RBZ chính thức!",
            "runtime_source"    => "recovery_required_blocked",
            "su_exe_dir"        => su_dir
          }
        end

        act_res = activate_pending_update_if_ready!(primary_plugins_root, bridge_dir)
        if act_res["recovery_required"] || act_res["ok"] == false
          @spawned_by_self = false
          @spawned_pid = 0
          @ipc_token = ""
          return {
            "alive"             => false,
            "recovery_required" => true,
            "port"              => 0,
            "pid"               => 0,
            "ipc_token"         => "",
            "error_code"        => (act_res["code"] || "PENDING_ACTIVATION_FAILED").to_s,
            "error"             => "Kích hoạt bản cập nhật chờ khởi động lại thất bại. Vui lòng cài lại tệp .RBZ chính thức!",
            "runtime_source"    => "recovery_required_blocked",
            "su_exe_dir"        => su_dir
          }
        end
      end

      pend_info = pending_restart_info
      port, already_alive = resolve_bridge_port
      if already_alive
        return {
          "alive"                  => true,
          "port"                   => port,
          "pid"                    => @spawned_pid,
          "ipc_token"              => @ipc_token.to_s,
          "runtime_source"         => @runtime_source,
          "su_exe_dir"             => su_dir,
          "pending_restart"        => pend_info["pending_restart"],
          "pending_target_version" => pend_info["target_version"]
        }
      end

      server_py = File.join(bridge_dir, "map_bridge_server.py")
      unless File.file?(server_py)
        return {
          "alive"          => false,
          "port"           => port,
          "pid"            => 0,
          "ipc_token"      => "",
          "error_code"     => "MISSING_BRIDGE_SCRIPT",
          "runtime_source" => "missing_bridge_script",
          "su_exe_dir"     => su_dir
        }
      end

      intact_ok = false
      unless dev_source_protected_bridge?(bridge_dir)
        intact_ok = try_unpack_offline_bundle!(bridge_dir)
        sync_cached_hotpatch_pyd!(bridge_dir) if intact_ok
      end

      candidate_python_bins(bridge_dir, already_intact: intact_ok).each do |pair|
        py_bin = pair[0]
        src_tag = pair[1]
        child_pid, fresh_ipc = spawn_bridge_candidate_process!(py_bin, src_tag, server_py, port, su_dir, parent_pid, bridge_dir)
        next unless child_pid && child_pid > 0

        25.times do
          if probe_mapskp_bridge?(port, fresh_ipc, child_pid)
            @active_port = port
            @ipc_token = fresh_ipc
            @spawned_pid = child_pid
            @spawned_by_self = true
            @runtime_source = src_tag
            return {
              "alive"                  => true,
              "port"                   => port,
              "pid"                    => child_pid,
              "ipc_token"              => @ipc_token,
              "runtime_source"         => @runtime_source,
              "su_exe_dir"             => su_dir,
              "pending_restart"        => pend_info["pending_restart"],
              "pending_target_version" => pend_info["target_version"]
            }
          end
          sleep(0.12)
        end
      end

      @spawned_by_self = false
      @spawned_pid = 0
      @ipc_token = ""
      {
        "alive"          => false,
        "port"           => port,
        "pid"            => 0,
        "ipc_token"      => "",
        "error_code"     => "PYTHON_RUNTIME_UNVERIFIED_OR_FAILED",
        "error"          => build_bridge_boot_failure_message,
        "runtime_source" => "missing_or_unverified_python_runtime",
        "su_exe_dir"     => su_dir
      }
    end

    def self.bridge_boot_log_file
      File.join(app_state_root, "bridge_boot_last.log")
    end

    def self.build_bridge_boot_failure_message
      base_msg = "Không thể khởi động cầu nối bảo mật MapSKP trên máy này."
      log_fp = bridge_boot_log_file
      if File.file?(log_fp) && !windows_reparse_point?(log_fp) && File.size(log_fp) > 0 && File.size(log_fp) <= 65_536
        tail = File.read(log_fp, encoding: "UTF-8").lines.map(&:strip).reject(&:empty?).last.to_s
        return "#{base_msg} (#{tail[0, 160]})" unless tail.empty?
      end
      base_msg
    rescue StandardError
      "Không thể khởi động cầu nối bảo mật MapSKP trên máy này."
    end

    def self.spawn_bridge_candidate_process!(py_bin, src_tag, server_py, port, su_dir, parent_pid, bridge_dir)
      fresh_ipc = SecureRandom.hex(24)
      spawn_env = {
        "PYTHONHOME"              => nil,
        "PYTHONPATH"              => nil,
        "PYTHONNOUSERSITE"        => (src_tag == "embedded_runtime" ? "1" : nil),
        "PYTHONDONTWRITEBYTECODE" => (src_tag == "embedded_runtime" ? "1" : nil),
        "PYTHONUTF8"              => "1",
        "MAPSKP_BRIDGE_PORT"      => port.to_s,
        "MAPSKP_SU_EXE_DIR"       => su_dir.to_s,
        "MAPSKP_IPC_TOKEN"        => fresh_ipc
      }
      args = [py_bin, "-X", "utf8", server_py, "--port", port.to_s]
      unless su_dir.to_s.empty?
        args << "--su-exe-dir"
        args << su_dir.to_s
      end
      if parent_pid.to_i > 0
        args << "--parent-pid"
        args << parent_pid.to_i.to_s
      end

      spawn_cwd = (Dir.tmpdir rescue nil).to_s
      spawn_cwd = bridge_dir if spawn_cwd.empty? || !Dir.exist?(spawn_cwd)

      err_target = File::NULL
      log_fp = bridge_boot_log_file
      begin
        FileUtils.mkdir_p(File.dirname(log_fp))
        if !path_has_reparse_ancestor?(log_fp, app_state_root) && (!File.exist?(log_fp) || !windows_reparse_point?(log_fp))
          err_target = [log_fp, "wb"]
        end
      rescue StandardError
        err_target = File::NULL
      end

      child_pid = Process.spawn(spawn_env, *args, chdir: spawn_cwd, close_others: true, :out => File::NULL, :err => err_target)
      Process.detach(child_pid)
      [child_pid, fresh_ipc]
    rescue StandardError
      [0, ""]
    end

    # Khởi tạo cầu nối theo máy trạng thái trên luồng chính của SketchUp (0% Thread.new bị C++ GetMessage bỏ đói, 0ms sleep đơ UI)
    def self.begin_bridge_boot_session!(bridge_dir, parent_pid = 0, su_exe_dir_override: nil)
      cleanup_legacy_ipc_token_file!
      su_dir = su_exe_dir_override.nil? ? sketchup_exe_dir : su_exe_dir_override.to_s
      primary_plugins_root = File.expand_path("../..", bridge_dir.to_s).tr("\\", "/").chomp("/")

      if !dev_source_protected_bridge?(bridge_dir)
        rec_res = recover_interrupted_update_if_needed!(primary_plugins_root)
        if rec_res["recovery_required"] || rec_res["ok"] == false
          @spawned_by_self = false
          @spawned_pid = 0
          @ipc_token = ""
          return {
            "state"  => "done",
            "result" => {
              "alive"             => false,
              "recovery_required" => true,
              "port"              => 0,
              "pid"               => 0,
              "ipc_token"         => "",
              "error_code"        => (rec_res["code"] || "RECOVERY_REQUIRED").to_s,
              "error"             => "Bản cập nhật trước bị gián đoạn và chưa thể tự khôi phục đồng bộ (#{rec_res['code'] || 'RECOVERY_REQUIRED'}). Vui lòng cài lại tệp .RBZ chính thức!",
              "runtime_source"    => "recovery_required_blocked",
              "su_exe_dir"        => su_dir
            }
          }
        end

        act_res = activate_pending_update_if_ready!(primary_plugins_root, bridge_dir)
        if act_res["recovery_required"] || act_res["ok"] == false
          @spawned_by_self = false
          @spawned_pid = 0
          @ipc_token = ""
          return {
            "state"  => "done",
            "result" => {
              "alive"             => false,
              "recovery_required" => true,
              "port"              => 0,
              "pid"               => 0,
              "ipc_token"         => "",
              "error_code"        => (act_res["code"] || "PENDING_ACTIVATION_FAILED").to_s,
              "error"             => "Kích hoạt bản cập nhật chờ khởi động lại thất bại. Vui lòng cài lại tệp .RBZ chính thức!",
              "runtime_source"    => "recovery_required_blocked",
              "su_exe_dir"        => su_dir
            }
          }
        end
      end

      pend_info = pending_restart_info
      port, already_alive = resolve_bridge_port
      if already_alive
        return {
          "state"  => "done",
          "result" => {
            "alive"                  => true,
            "port"                   => port,
            "pid"                    => @spawned_pid,
            "ipc_token"              => @ipc_token.to_s,
            "runtime_source"         => @runtime_source,
            "su_exe_dir"             => su_dir,
            "pending_restart"        => pend_info["pending_restart"],
            "pending_target_version" => pend_info["target_version"]
          }
        }
      end

      server_py = File.join(bridge_dir, "map_bridge_server.py")
      unless File.file?(server_py)
        return {
          "state"  => "done",
          "result" => {
            "alive"          => false,
            "port"           => port,
            "pid"            => 0,
            "ipc_token"      => "",
            "error_code"     => "MISSING_BRIDGE_SCRIPT",
            "error"          => "Thiếu tệp khởi chạy cầu nối MapSKP.",
            "runtime_source" => "missing_bridge_script",
            "su_exe_dir"     => su_dir
          }
        }
      end

      intact_ok = false
      unless dev_source_protected_bridge?(bridge_dir)
        intact_ok = try_unpack_offline_bundle!(bridge_dir)
        sync_cached_hotpatch_pyd!(bridge_dir) if intact_ok
      end

      cands = candidate_python_bins(bridge_dir, already_intact: intact_ok)
      if cands.empty?
        @spawned_by_self = false
        @spawned_pid = 0
        @ipc_token = ""
        return {
          "state"  => "done",
          "result" => {
            "alive"          => false,
            "port"           => port,
            "pid"            => 0,
            "ipc_token"      => "",
            "error_code"     => "PYTHON_RUNTIME_UNVERIFIED_OR_FAILED",
            "error"          => "Không tìm thấy hoặc chưa xác minh được bộ thực thi Python nhúng của MapSKP.",
            "runtime_source" => "missing_or_unverified_python_runtime",
            "su_exe_dir"     => su_dir
          }
        }
      end

      ctx = {
        "state"       => "polling",
        "bridge_dir"  => bridge_dir,
        "server_py"   => server_py,
        "port"        => port,
        "su_dir"      => su_dir,
        "parent_pid"  => parent_pid.to_i,
        "pend_info"   => pend_info,
        "candidates"  => cands,
        "cand_idx"    => -1,
        "child_pid"   => 0,
        "fresh_ipc"   => "",
        "src_tag"     => "",
        "ticks_spent" => 0,
        "max_ticks"   => 50
      }
      advance_to_next_bridge_candidate!(ctx)
    end

    def self.advance_to_next_bridge_candidate!(ctx)
      cands = ctx["candidates"] || []
      while (ctx["cand_idx"] + 1) < cands.length
        ctx["cand_idx"] += 1
        pair = cands[ctx["cand_idx"]]
        cpid, ipc = spawn_bridge_candidate_process!(
          pair[0],
          pair[1],
          ctx["server_py"],
          ctx["port"],
          ctx["su_dir"],
          ctx["parent_pid"],
          ctx["bridge_dir"]
        )
        if cpid && cpid > 0
          ctx["child_pid"]   = cpid
          ctx["fresh_ipc"]   = ipc
          ctx["src_tag"]     = pair[1]
          ctx["ticks_spent"] = 0
          return ctx
        end
      end

      @spawned_by_self = false
      @spawned_pid = 0
      @ipc_token = ""
      {
        "state"  => "done",
        "result" => {
          "alive"          => false,
          "port"           => ctx["port"],
          "pid"            => 0,
          "ipc_token"      => "",
          "error_code"     => "PYTHON_RUNTIME_UNVERIFIED_OR_FAILED",
          "error"          => build_bridge_boot_failure_message,
          "runtime_source" => "missing_or_unverified_python_runtime",
          "su_exe_dir"     => ctx["su_dir"]
        }
      }
    end

    def self.poll_bridge_boot_session!(ctx)
      return ctx unless ctx.is_a?(Hash) && ctx["state"] == "polling"
      port      = ctx["port"].to_i
      fresh_ipc = ctx["fresh_ipc"].to_s
      child_pid = ctx["child_pid"].to_i
      pend_info = ctx["pend_info"] || {}

      if child_pid > 0 && probe_mapskp_bridge?(port, fresh_ipc, child_pid, connect_timeout: 0.12, io_timeout: 0.25)
        @active_port     = port
        @ipc_token       = fresh_ipc
        @spawned_pid     = child_pid
        @spawned_by_self = true
        @runtime_source  = ctx["src_tag"].to_s
        return {
          "state"  => "done",
          "result" => {
            "alive"                  => true,
            "port"                   => port,
            "pid"                    => child_pid,
            "ipc_token"              => @ipc_token,
            "runtime_source"         => @runtime_source,
            "su_exe_dir"             => ctx["su_dir"].to_s,
            "pending_restart"        => pend_info["pending_restart"],
            "pending_target_version" => pend_info["target_version"]
          }
        }
      end

      ctx["ticks_spent"] = ctx["ticks_spent"].to_i + 1
      if ctx["ticks_spent"] >= ctx["max_ticks"].to_i
        return advance_to_next_bridge_candidate!(ctx)
      end
      ctx
    end
  end
end
