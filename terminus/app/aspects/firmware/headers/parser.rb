# frozen_string_literal: true

require "pipeable"
require "refinements/hash"

module Terminus
  module Aspects
    module Firmware
      module Headers
        # Parses firmware HTTP headers into records.
        class Parser
          include Deps[
            :logger,
            model_name_transformer: "aspects.firmware.headers.transformers.model_name",
            sensors_transformer: "aspects.firmware.headers.transformers.sensors"
          ]
          include Pipeable

          using Refinements::Hash

          def initialize(
            schema: Terminus::Schemas::Firmware::Header,
            model: Terminus::Models::Firmware::Header,
            **
          )
            @schema = schema
            @model = model
            super(**)
          end

          def call headers
            logger.debug(tags: tags(headers)) { "Processing device request headers." }

            pipe headers,
                 validate(schema, as: :to_h),
                 use(model_name_transformer),
                 use(sensors_transformer),
                 to(model, :for)
          end

          private

          attr_reader :schema, :model

          def tags(headers) = [headers.slice(*schema.key_map.map(&:name)).symbolize_keys]
        end
      end
    end
  end
end
