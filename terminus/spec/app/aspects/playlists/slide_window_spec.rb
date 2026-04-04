# frozen_string_literal: true

require "hanami_helper"

RSpec.describe Terminus::Aspects::Playlists::SlideWindow, :db do
  subject :slide_window do
    described_class.new playlist_repository.with_screens.by_pk(playlist.id).one
  end

  let(:playlist) { Factory[:playlist] }
  let(:screen) { Factory[:screen, :with_image] }
  let(:item) { Factory[:playlist_item, playlist_id: playlist.id, screen_id: screen.id] }
  let(:playlist_repository) { Terminus::Repositories::Playlist.new }

  describe "#item" do
    it "answers nil when playlist doesn't have current item" do
      expect(slide_window.item).to be(nil)
    end

    it "answers item when playlist has current item" do
      playlist_repository.update playlist.id, current_item_id: item.id
      described_class.new playlist_repository.with_screens.by_pk(playlist.id).one

      expect(slide_window.item.id).to eq(item.id)
    end
  end

  describe "#screens" do
    let :items do
      (1..3).map do |index|
        Factory[
          :playlist_item,
          playlist_id: playlist.id,
          screen_id: Factory[:screen, :with_image, id: index].id,
          position: index
        ]
      end
    end

    it "centers on first screen when there isn't a current item" do
      items
      screen_ids = slide_window.screens.map(&:id)

      expect(screen_ids).to eq([3, 1, 2])
    end

    it "answers nil when there are no screens" do
      expect(slide_window.screens).to be(nil)
    end

    it "centers on specific screen (last screen) when current item is set" do
      items
      playlist_repository.update_current_item playlist, items.last

      expect(slide_window.screens.map(&:id)).to eq([2, 3, 1])
    end

    it "centers on specific screen (middle screen) when screen ID is supplied" do
      items
      playlist_repository.update_current_item playlist, items[1]

      expect(slide_window.screens.map(&:id)).to eq([1, 2, 3])
    end
  end
end
