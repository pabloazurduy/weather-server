# auto_register: false
# frozen_string_literal: true

require "refinements/array"

module Terminus
  module Aspects
    module Playlists
      # The playlist slideshow window of current item and associated slides.
      class SlideWindow
        include Deps[repository: "repositories.playlist"]

        using Refinements::Array

        attr_reader :playlist

        def initialize(playlist, **)
          super(**)
          @playlist = playlist
        end

        def item = playlist.current_item

        def screens id = nil
          enumerable = playlist.screens.ring

          return enumerable.first unless item

          enumerable.find do |before, current, after|
            break before, current, after if current.id == (id || item.screen_id)
          end
        end
      end
    end
  end
end
