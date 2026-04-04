# frozen_string_literal: true

module Terminus
  module Contracts
    module Models
      # The contract for model creation.
      class Create < Contract
        config.messages.namespace = :model

        params { required(:model).filled Schemas::Models::Upsert }

        rule model: :mime_type, &Rules::ImageMimeType
      end
    end
  end
end
