# frozen_string_literal: true

require "dry/monads"

module Terminus
  module Aspects
    module Models
      # Clones an existing model.
      class Cloner
        include Deps[repository: "repositories.model"]
        include Dry::Monads[:result]

        def call(id, **overrides)
          original = repository.find id
          attributes = {label: "#{original.label} Clone", name: "#{original.name}_clone"}

          Success create(original, attributes, overrides)
        rescue ROM::SQL::UniqueConstraintError => error
          build_failure error.message
        end

        private

        def create original, attributes, overrides
          repository.create(
            **original.to_h.except(:id, :created_at, :updated_at),
            **attributes,
            **overrides
          )
        end

        def build_failure message
          match = message.match(/Key \((?<key>[^)]+)\)/)
          Failure match[:key].to_sym => ["must be unique"]
        end
      end
    end
  end
end
