# frozen_string_literal: true

module Terminus
  module Aspects
    module Models
      DEFAULTS = {
        mime_type: "image/png",
        colors: 2,
        bit_depth: 1,
        rotation: 0,
        offset_x: 0,
        offset_y: 0,
        scale_factor: 1,
        width: 0,
        height: 0,
        palette_names: nil,
        css: nil
      }.freeze
    end
  end
end
