# frozen_string_literal: true

require "hanami/view"
require "initable"
require "refinements/array"

module Terminus
  module Views
    module Parts
      # The model presenter.
      class Model < Hanami::View::Part
        include Initable[json_formatter: Aspects::JSONFormatter]

        using Refinements::Array

        def alpine_palettes
          Array(palette_names).map { %('#{it}') }
                              .join(",")
                              .then { "[#{it}]" }
        end

        def dimensions = "#{width}x#{height}"

        def formatted_css = json_formatter.call css

        def kind_label
          case kind
            when "byod", "trmnl" then kind.upcase
            else kind.capitalize
          end
        end

        def palettes = palette_names.to_sentence
      end
    end
  end
end
