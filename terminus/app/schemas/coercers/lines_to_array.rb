# auto_register: false
# frozen_string_literal: true

require "refinements/hash"

module Terminus
  module Schemas
    # Coerces a key's line delimited string value into an array.
    module Coercers
      using Refinements::Hash

      LinesToArray = lambda do |key, result|
        Hash(result.to_h).transform_value!(key) { String(it).split(/\r\n|\n|\r|\s/) }
      end
    end
  end
end
