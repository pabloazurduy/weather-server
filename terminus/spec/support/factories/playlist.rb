# frozen_string_literal: true

Factory.define :playlist, relation: :playlist do |factory|
  factory.sequence(:label) { "Playlist #{it}" }
  factory.sequence(:name) { "playlist_#{it}" }
end
