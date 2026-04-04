# frozen_string_literal: true

require "dry/monads"
require "initable"

module Terminus
  module Aspects
    module Firmware
      module Headers
        module Transformers
          # Transforms a model name to a name that looked up in the database.
          class ModelName
            include Deps[:logger]

            include Initable[
              key: :HTTP_MODEL,
              map: {
                "og" => "og_plus",
                "reTerminal E1001" => "seeed_e1001",
                "reTerminal E1002" => "seeed_e1002",
                "seeed_esp32c3" => "seeed_e1001",
                "seeed_esp32s3" => "seeed_e1002",
                "waveshare" => "waveshare_4_26",
                "x" => "v2",
                "xiao_epaper_display" => "og_plus",
                "XTEINK_X4" => "xteink_x4"
              },
              fallback: "og_plus"
            ]

            include Dry::Monads[:result]

            def call headers
              rename(headers[key]).bind { |value| Success headers.merge!(key => value) }
            end

            private

            def rename original
              value = String map[original]

              return Success value unless value.empty?

              logger.debug do
                "Unknown name when transforming #{key} header: #{original.inspect}. " \
                "Using fallback: #{fallback}."
              end

              Success fallback
            end
          end
        end
      end
    end
  end
end
