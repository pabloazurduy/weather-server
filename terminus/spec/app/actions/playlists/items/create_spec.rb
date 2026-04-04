# frozen_string_literal: true

require "hanami_helper"

RSpec.describe Terminus::Actions::Playlists::Items::Create, :db do
  subject(:action) { described_class.new }

  describe "#call" do
    let(:playlist) { Factory[:playlist] }
    let(:screen) { Factory[:screen, :with_image] }
    let(:playlist_repository) { Terminus::Repositories::Playlist.new }

    let :params do
      {
        playlist_id: playlist.id,
        playlist_item: {
          screen_id: screen.id
        }
      }
    end

    it "updates playlist with created item when there is no current item" do
      Rack::MockRequest.new(action).post("", params:)

      expect(playlist_repository.find(playlist.id)).to have_attributes(
        current_item_id: kind_of(Integer)
      )
    end

    it "answers unprocessable entity with invalid parameters" do
      params.delete :playlist_item
      response = Rack::MockRequest.new(action).post("", params:)

      expect(response.status).to eq(422)
    end

    it "answers unprocessable entity with invalid playlist ID" do
      params[:playlist_id] = 666
      response = Rack::MockRequest.new(action).post("", params:)

      expect(response.status).to eq(422)
    end
  end
end
