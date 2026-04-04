# frozen_string_literal: true

require "dry/core"

module Terminus
  module Structs
    # The palette struct.
    class Palette < DB::Struct
      def screen_attributes = {grays:, color_codes: colors}
    end
  end
end
