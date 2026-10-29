@Override
    public Object deserialize(JsonParser p, DeserializationContext ctxt)
        throws JacksonException
    {
        Object value;

        // First: the case of having deserializer for non-String input for delegating
        // Creator method
        if (_deser != null) {
            value = _deser.deserialize(p, ctxt);

        // Second: property- and delegating-creators
        } else if (_hasArgs) {
            // 30-Mar-2020, tatu: For properties-based one, MUST get JSON Object (before
            //   2.11, was just assuming match)
            if (_creatorProps != null) {
                if (p.isExpectedStartObjectToken()) {
                    PropertyBasedCreator pc = _propCreator;
                    if (pc == null) {
                        _propCreator = pc = PropertyBasedCreator.construct(ctxt,
                                _valueInstantiator, _creatorProps,
                                ctxt.isEnabled(MapperFeature.ACCEPT_CASE_INSENSITIVE_PROPERTIES));
                    }
                    // p.nextToken();
                    return deserializeEnumUsingPropertyBased(p, ctxt, pc);
                }
                // If value cannot possibly be delegating-creator,
                if (!_valueInstantiator.canCreateFromString()) {
                    final JavaType targetType = getValueType(ctxt);
                    final JsonToken t = p.currentToken();
                    return ctxt.reportInputMismatch(targetType,
                        "Input mismatch reading Enum %s: properties-based `@JsonCreator` (%s) expects Object Value, got %s (`JsonToken.%s`)",
                        ClassUtil.getTypeDescription(targetType), _factory,
                        JsonToken.valueDescFor(t), t.name());
                }
            }
            // 12-Oct-2021, tatu: We really should only get here if and when String
            //    value is expected; otherwise Deserializer should have been used earlier
            // 14-Jan-2022, tatu: as per [databind#3369] need to consider structured
            //    value types (Object, Array) as well.
            // 15-Nov-2022, tatu: Fix for [databind#3655] requires handling of possible
            //    unwrapping, do it here
            JsonToken t = p.currentToken();
            boolean unwrapping = (t == JsonToken.START_ARRAY)
                    && ctxt.isEnabled(DeserializationFeature.UNWRAP_SINGLE_VALUE_ARRAYS);
            if (unwrapping) {
                t = p.nextToken();
            }
            // 24-Nov-2024, tatu: New! "Scalar from Object" (mostly for XML) -- see
            //   https://github.com/FasterXML/jackson-databind/issues/4807
            if (t == JsonToken.START_OBJECT) {
                value = ctxt.extractScalarFromObject(p, this, _valueClass);
                // 17-May-2025, tatu: [databind#4656] need to check for `null`
                if (value == null) {
                    return ctxt.handleUnexpectedToken(_valueClass, p);
                }
            } else if ((t == null) || !t.isScalarValue()) {
                // Could argue we should throw an exception but...
                // 01-Jun-2023, tatu: And now we will finally do it!
                final JavaType targetType = getValueType(ctxt);
                return ctxt.reportInputMismatch(targetType,
                    "Input mismatch reading Enum %s: properties-based `@JsonCreator` (%s) expects String Value, got %s (`JsonToken.%s`)",
                    ClassUtil.getTypeDescription(targetType), _factory,
                    JsonToken.valueDescFor(t), t.name());
            } else {
                value = p.getValueAsString();
            }
            if (unwrapping) {
                if (p.nextToken() != JsonToken.END_ARRAY) {
                    handleMissingEndArrayForSingle(p, ctxt);
                }
            }
        } else { // zero-args; just skip whatever value there may be
            p.skipChildren();
            try {
                return _factory.call();
            } catch (Exception e) {
                Throwable t = ClassUtil.throwRootCauseIfJacksonE(e);
                return ctxt.handleInstantiationProblem(_valueClass, null, t);
            }
        }
        try {
            return _factory.callOnWith(_valueClass, value);
        } catch (Exception e) {
            Throwable t = ClassUtil.throwRootCauseIfJacksonE(e);
            if (t instanceof IllegalArgumentException) {
                // [databind#4979]: unknown as default
                if (ctxt.isEnabled(EnumFeature.READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE)) {
                    // ... only if we DO have a default
                    if (_defaultValue != null) {
                        return _defaultValue;
                    }
                }
                // [databind#1642]: unknown as null
                if (ctxt.isEnabled(EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)) {
                    return null;
                }
                // 12-Oct-2021, tatu: Should probably try to provide better exception since
                //   we likely hit argument incompatibility... Or can this happen?
            }
            return ctxt.handleInstantiationProblem(_valueClass, value, t);
        }
    }