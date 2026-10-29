@Override
    public EnumMap<?,?> deserialize(JsonParser p, DeserializationContext ctxt,
            EnumMap result)
        throws JacksonException
    {
        // [databind#631]: Assign current value, to be accessible by custom deserializers
        p.assignCurrentValue(result);

        String keyStr;
        if (p.isExpectedStartObjectToken()) {
            keyStr = p.nextName();
        } else {
            JsonToken t = p.currentToken();
            if (t != JsonToken.PROPERTY_NAME) {
                if (t == JsonToken.END_OBJECT) {
                    return result;
                }
                ctxt.reportWrongTokenException(this, JsonToken.PROPERTY_NAME, null);
            }
            keyStr = p.currentName();
        }
        if (keyStr == null) {
            return result;
        }

        // Need to resolve ObjectIds (forward refs)?
        final MapDeserializer.MapReferringAccumulator referringAccumulator =
            (_valueDeserializer.getObjectIdReader(ctxt) == null)
                    ? null
                    : new MapDeserializer.MapReferringAccumulator(
                            _containerType.getContentType().getRawClass(), result);

        for (; keyStr != null; keyStr = p.nextName()) {
            // but we need to let key deserializer handle it separately, nonetheless
            Enum<?> key = (Enum<?>) _keyDeserializer.deserializeKey(keyStr, ctxt);
            JsonToken t = p.nextToken();
            if (key == null) {
                if (ctxt.isEnabled(EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)) {
                    return (EnumMap<?,?>) ctxt.handleWeirdStringValue(_enumClass, keyStr,
                            "value not one of declared Enum instance names for %s",
                            ClassUtil.getTypeDescription(_containerType.getKeyType()));
                }
                p.skipChildren();
                continue;
            }
            // And then the value...
            // note: MUST check for nulls separately: deserializers will
            // not handle them (and maybe fail or return bogus data)
            Object value;

            try {
                if (t == JsonToken.VALUE_NULL) {
                    if (_skipNullValues) {
                        continue;
                    }
                    value = null;
                } else {
                    value = _deserializeNoNullChecks(p, ctxt);
                }

                if (value == null) {
                    value = _nullProvider.getNullValue(ctxt);

                    if (value == null && _skipNullValues) {
                        continue;
                    }
                }
                if (referringAccumulator == null) {
                    result.put(key, value);
                } else {
                    referringAccumulator.put(key, value);
                }
            } catch (UnresolvedForwardReference reference) {
                _handleUnresolvedReference(ctxt, referringAccumulator, key, reference);
            } catch (Exception e) {
                return wrapAndThrow(ctxt, e, result, keyStr);
            }
        }
        return result;
    }