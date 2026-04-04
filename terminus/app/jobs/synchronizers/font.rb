# auto_register: false
# frozen_string_literal: true

module Terminus
  module Jobs
    module Synchronizers
      # Synchronizes TRMNL Framework fonts for local use.
      class Font < Base
        include Deps["aspects.fonts.synchronizer"]

        sidekiq_options queue: "within_1_minute"

        def perform = synchronizer.call
      end
    end
  end
end
