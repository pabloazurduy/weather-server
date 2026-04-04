# auto_register: false
# frozen_string_literal: true

module Terminus
  module Schemas
    module Models
      # Defines model upsert schema.
      Upsert = Dry::Schema.Params do
        required(:name).filled :string
        required(:label).filled :string
        optional(:description).maybe :string
        optional(:mime_type).filled :string
        optional(:colors).filled :integer
        optional(:bit_depth).filled :integer
        optional(:rotation).filled :integer
        optional(:offset_x).filled :integer
        optional(:offset_y).filled :integer
        optional(:scale_factor).filled :float
        optional(:width).filled :integer
        optional(:height).filled :integer
        optional(:palette_names).maybe :array
        optional(:css).maybe :hash

        after(:value_coercer, &Coercers::LinesToArray.curry[:palette_names])
        after(:value_coercer, &Coercers::JSONToHash.curry[:css])
      end
    end
  end
end
