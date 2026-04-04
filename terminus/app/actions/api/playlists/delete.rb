# frozen_string_literal: true

module Terminus
  module Actions
    module API
      module Playlists
        # The delete action.
        class Delete < Base
          include Deps[repository: "repositories.playlist"]
          include Initable[serializer: Serializers::Playlist]

          def handle request, response
            playlist = repository.with_items.by_pk(request.params[:id]).one

            response.body = if playlist
                              repository.delete playlist.id
                              {data: serializer.new(playlist).to_h}.to_json
                            else
                              {data: {}}.to_json
                            end
          end
        end
      end
    end
  end
end
