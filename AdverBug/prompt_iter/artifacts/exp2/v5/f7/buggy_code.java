protected final Float _parseFloat(JsonParser p, DeserializationContext ctxt)
            throws JacksonException
        {
            String text;
            switch (p.currentTokenId()) {
            case JsonTokenId.ID_STRING:
                text = p.getString();
                break;
            case JsonTokenId.ID_NULL: // null fine for non-primitive
                return (Float) getNullValue(ctxt);
            case JsonTokenId.ID_NUMBER_INT:
                final CoercionAction act = _checkIntToFloatCoercion(p, ctxt, _valueClass);
                if (act == CoercionAction.AsNull) {
                    return (Float) getNullValue(ctxt);
                }
                if (act == CoercionAction.AsEmpty) {
                    return (Float) getEmptyValue(ctxt);
                }
                // fall through to coerce
            case JsonTokenId.ID_NUMBER_FLOAT:
                return p.getFloatValue();
            case JsonTokenId.ID_START_ARRAY:
                return _deserializeFromArray(p, ctxt);
            // 29-Jun-2020, tatu: New! "Scalar from Object" (mostly for XML)
            case JsonTokenId.ID_START_OBJECT:
                text = ctxt.extractScalarFromObject(p, this, _valueClass);
                // 17-May-2025, tatu: [databind#4656] need to check for `null`
                if (text == null) {
                    break;
                }
                // fall through
            default:
                return (Float) ctxt.handleUnexpectedToken(getValueType(ctxt), p);
            }

            // 18-Nov-2020, tatu: Special case, Not-a-Numbers as String need to be
            //     considered "native" representation as JSON does not allow as numbers,
            //     and hence not bound by coercion rules
            {
                Float nan = _checkFloatSpecialValue(text);
                if (nan != null) {
                    return nan;
                }
            }
            final CoercionAction act = _checkFromStringCoercion(ctxt, text);
            if (act == CoercionAction.AsNull) {
                return (Float) getNullValue(ctxt);
            }
            if (act == CoercionAction.AsEmpty) {
                return (Float) getEmptyValue(ctxt);
            }
            text = text.trim();
            if (_checkTextualNull(ctxt, text)) {
                return (Float) getNullValue(ctxt);
            }
            // 09-Dec-2023, tatu: To avoid parser having to validate input, pre-validate:
            if (NumberInput.looksLikeValidNumber(text)) {
                p.streamReadConstraints().validateFPLength(text.length());
                try {
                    return NumberInput.parseFloat(text, p.isEnabled(StreamReadFeature.USE_FAST_DOUBLE_PARSER));
                } catch (IllegalArgumentException iae) { }
            }
            return (Float) ctxt.handleWeirdStringValue(_valueClass, text,
                    "not a valid `Float` value");
        }