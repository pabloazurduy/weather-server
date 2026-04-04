# frozen_string_literal: true

require "hanami_helper"

RSpec.describe Terminus::Serializers::PlaylistItem do
  subject(:serializer) { described_class.new playlist_item }

  let(:playlist_item) { Factory.structs[:playlist_item, **attributes] }

  let :attributes do
    {
      screen_id: 1,
      position: 1,
      created_at: "2025-01-01T10:10:10+0000",
      updated_at: "2025-01-01T10:10:10+0000"
    }
  end

  describe "#to_h" do
    it "answers explicit hash" do
      expect(serializer.to_h).to eq(id: playlist_item.id, **attributes)
    end
  end
end
