# frozen_string_literal: true

Factory.define :palette, relation: :palette do |factory|
  factory.sequence(:label) { "Palette #{it}" }
  factory.sequence(:name) { "palette_#{it}" }
  factory.kind { "terminus" }
  factory.grays 2
  factory.colors []
  factory.framework_class "screen--1bit"
end
