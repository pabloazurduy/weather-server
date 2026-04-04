# auto_register: false
# frozen_string_literal: true

module Terminus
  module Serializers
    # A playlist item serializer for specific keys.
    class PlaylistItem
      KEYS = %i[id screen_id position created_at updated_at].freeze

      def initialize record, keys: KEYS, transformer: Transformers::Time
        @record = record
        @keys = keys
        @transformer = transformer
      end

      def to_h
        attributes = record.to_h.slice(*keys)
        attributes.transform_values!(&transformer)
        attributes
      end

      private

      attr_reader :record, :keys, :transformer
    end
  end
end
