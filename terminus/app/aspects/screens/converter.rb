# frozen_string_literal: true

module Terminus
  module Aspects
    module Screens
      # Converts to greyscale image based on MIME Type.
      class Converter
        include Deps["aspects.screens.converters.color", "aspects.screens.converters.monochrome"]

        def call(mold) = mold.color? ? color.call(mold) : monochrome.call(mold)
      end
    end
  end
end
