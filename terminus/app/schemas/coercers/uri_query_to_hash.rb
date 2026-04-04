# auto_register: false
# frozen_string_literal: true

require "json"
require "refinements/hash"

module Terminus
  module Schemas
    # Coerces key's URI query parameters value into a hash.
    module Coercers
      using Refinements::Hash

      URIQueryToHash = lambda do |key, result|
        Hash(result.to_h).transform_value!(key) do |value|
          Rack::Utils.parse_query value unless String(value).empty?
        end
      end
    end
  end
end
