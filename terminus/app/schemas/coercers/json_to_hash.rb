# auto_register: false
# frozen_string_literal: true

require "json"
require "refinements/hash"

module Terminus
  module Schemas
    # Coerces a key's JSON value into a hash.
    module Coercers
      using Refinements::Hash

      JSONToHash = lambda do |key, result|
        attributes = Hash result.to_h
        attributes.transform_value!(key) { JSON it if it }
      rescue JSON::ParserError
        attributes
      end
    end
  end
end
