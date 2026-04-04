# frozen_string_literal: true

require "initable"
require "refinements/pathname"

module Terminus
  module Aspects
    module Fonts
      # Synchronizes TRMNL Framework fonts for local use.
      class Synchronizer
        include Deps[:settings, "aspects.downloader"]
        include Initable[
          root_uri: "https://trmnl.com/fonts",
          names: %w[
            BlockKie.ttf
            dogicapixel.ttf
            dogicapixelbold.ttf
            Inter-Italic.ttf
            Inter.ttf
            NicoBold-Regular.ttf
            NicoClean-Regular.ttf
            NicoPups-Regular.ttf
          ]
        ]
        include Dry::Monads[:result]

        using Refinements::Pathname

        def call
          root = settings.fonts_root.make_dir

          delete_unknown_files_in root
          names.map { download_to root, it }
        end

        private

        def delete_unknown_files_in root
          root.files
              .map { it.basename.to_s }
              .then { |locals| locals - names }
              .each { root.join(it).delete }
        end

        def download_to root, name
          path = root.join name

          return Success path if path.exist?

          downloader.call("#{root_uri}/#{name}").fmap { |response| path.write response.body }
        end
      end
    end
  end
end
