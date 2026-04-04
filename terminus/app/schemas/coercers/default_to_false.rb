# auto_register: false
# frozen_string_literal: true

require "refinements/hash"

module Terminus
  module Schemas
    # Coerces a key's value to false when key is missing.
    module Coercers
      using Refinements::Hash

      DefaultToFalse = lambda do |key, result|
        return unless result.output

        attributes = Hash result.to_h
        attributes[key] = false unless result.key? key

        attributes
      end
    end
  end
end
