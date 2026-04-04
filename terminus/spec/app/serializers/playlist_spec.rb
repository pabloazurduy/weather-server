# frozen_string_literal: true

require "hanami_helper"

RSpec.describe Terminus::Serializers::Playlist, :db do
  subject :serializer do
    described_class.new Terminus::Repositories::Playlist.new.with_items.by_pk(item.playlist_id).one
  end

  let(:item) { Factory[:playlist_item] }

  describe "#to_h" do
    it "answers hash when nil" do
      serializer = described_class.new nil
      expect(serializer.to_h).to eq({})
    end

    it "answers hash with filled items" do
      playlist = item.playlist

      expect(serializer.to_h).to match(
        id: item.playlist_id,
        name: playlist.name,
        label: playlist.label,
        current_item_id: nil,
        mode: "automatic",
        items: [
          hash_including(
            id: item.id,
            screen_id: kind_of(Integer),
            position: kind_of(Integer),
            created_at: match_rfc_3339,
            updated_at: match_rfc_3339
          )
        ],
        created_at: match_rfc_3339,
        updated_at: match_rfc_3339
      )
    end

    it "answers hash with empty items" do
      playlist = Factory.structs[:playlist]
      serializer = described_class.new playlist

      expect(serializer.to_h).to eq(
        id: playlist.id,
        name: playlist.name,
        label: playlist.label,
        current_item_id: nil,
        mode: nil,
        items: [],
        created_at: nil,
        updated_at: nil
      )
    end
  end
end
