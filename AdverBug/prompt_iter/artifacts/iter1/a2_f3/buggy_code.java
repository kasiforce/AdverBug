@Override
    public Object deserializeFromObject(JsonParser p, DeserializationContext ctxt)
        throws JacksonException
    {
        // 30-Sep-2010, tatu: Need to allow use of @JsonCreator, so:
        if (_propertyBasedCreator != null) { // proper @JsonCreator
            return _deserializeUsingPropertyBased(p, ctxt);
        }
        if (_delegateDeserializer != null) {
            return _valueInstantiator.createUsingDelegate(ctxt,
                    _delegateDeserializer.deserialize(p, ctxt));
        }
        if (_beanType.isAbstract()) { // for good measure, check this too
            return ctxt.handleMissingInstantiator(handledType(), getValueInstantiator(), p,
                    "abstract type (need to add/enable type information?)");
        }
        boolean hasStringCreator = _valueInstantiator.canCreateFromString();
        boolean hasDefaultCtor = _valueInstantiator.canCreateUsingDefault();
        // and finally, verify we do have single-String arg constructor (if no @JsonCreator)
        if (!hasStringCreator && !hasDefaultCtor) {
            return ctxt.handleMissingInstantiator(handledType(), getValueInstantiator(), p,
                    "Throwable needs a default constructor, a single-String-arg constructor; or explicit @JsonCreator");
        }
        Throwable throwable = null;
        Object[] pending = null;
        Throwable[] suppressed = null;
        int pendingIx = 0;

        // [databind#6190]: `_needViewProcesing` only accounts for settable properties, but
        // "message"/"suppressed" may carry an explicit `@JsonView` without being bound as
        // one -- so consult those too, else their views would be ignored whenever no
        // regular property has any (as happens with `DEFAULT_VIEW_INCLUSION` enabled)
        final Class<?> activeView = (_needViewProcesing || _stdPropNames.hasExplicitViews())
                ? ctxt.getActiveView() : null;
        int ix = p.currentNameMatch(_propNameMatcher);
        for (; ; ix = p.nextNameMatch(_propNameMatcher)) {
            if (ix >= 0) {
                p.nextToken();
                SettableBeanProperty prop = _propsByIndex[ix];
                // Property not part of the active view must not be set from input.
                // Standard `Throwable` properties without explicit views have no view restrictions
                // configured, while those with explicit `@JsonView` honor them (see [databind#6190]).
                if ((activeView != null) && !prop.visibleInView(activeView)) {
                    _handleViewExcluded(p, ctxt, prop.getName(), activeView);
                    continue;
                }
                if (throwable != null) {
                    // 07-Dec-2023, tatu: [databind#4248] Interesting that "cause"
                    //    with `null` blows up. So, avoid.
                    // Same for "stackTrace" - setStackTrace(null) throws NPE
                    if (p.hasToken(JsonToken.VALUE_NULL)
                            && _shouldSkipNullValue(prop.getName())) {
                        continue;
                    }
                    prop.deserializeAndSet(p, ctxt, throwable);
                    continue;
                }
                // nope; need to defer
                if (pending == null) {
                    int len = _beanProperties.size();
                    pending = new Object[len + len];
                } else if (pendingIx == pending.length) {
                    // NOTE: only occurs with duplicate properties, possible
                    // with some formats (most notably XML; but possibly with
                    // JSON if duplicate detection not enabled). Most likely
                    // only occurs with malicious content so use linear buffer
                    // resize (no need to optimize performance)
                    pending = Arrays.copyOf(pending, pendingIx + 16);
                }
                pending[pendingIx++] = prop;
                pending[pendingIx++] = prop.deserialize(p, ctxt);
                continue;
            }
            if (ix != PropertyNameMatcher.MATCH_UNKNOWN_NAME) {
                if (ix == PropertyNameMatcher.MATCH_END_OBJECT) {
                    break;
                }
                return _handleUnexpectedWithin(p, ctxt, throwable);
            }
            // Maybe it's "message"?
            String propName = p.currentName();
            p.nextToken();
            // 04-Sep-2026, tatu: [databind#6188] Names compared against are the ones resolved
            //    at construction, so a `PropertyNamingStrategy` is accounted for; the
            //    case-insensitive compare remains for case-insensitive input matching
            if (_stdPropNames.message.equalsIgnoreCase(propName)) {
                // [databind#6190]: explicit `@JsonView` on "message" must be honored;
                // left unset, it is instantiated with `null` message after the loop
                if (!_visibleInView(_stdPropNames.messageViews, activeView)) {
                    _handleViewExcluded(p, ctxt, propName, activeView);
                    continue;
                }
                throwable = _instantiate(ctxt, hasStringCreator, p.getText());
                // any pending values?
                if (pending != null) {
                    for (int i = 0, len = pendingIx; i < len; i += 2) {
                        SettableBeanProperty prop = (SettableBeanProperty)pending[i];
                        Object value = pending[i+1];
                        // Skip null values for properties that don't accept them
                        if (value == null && _shouldSkipNullValue(prop.getName())) {
                            continue;
                        }
                        prop.set(ctxt, throwable, value);
                    }
                    pending = null;
                }
                continue;
            }

            if (_stdPropNames.suppressed.equalsIgnoreCase(propName)) {
                // [databind#6190]: explicit `@JsonView` on "suppressed" must be honored
                if (!_visibleInView(_stdPropNames.suppressedViews, activeView)) {
                    _handleViewExcluded(p, ctxt, propName, activeView);
                    continue;
                }
                // 07-Dec-2023, tatu: Not sure how/why, but JSON Null is otherwise
                //    not handled with such call so...
                if (p.hasToken(JsonToken.VALUE_NULL)) {
                    suppressed = null;
                } else {
                    // Inlined `DeserializationContext.readValue()` to minimize call depth
                    ValueDeserializer<Object> deser = ctxt.findRootValueDeserializer(
                            ctxt.constructType(Throwable[].class));
                    suppressed = (Throwable[]) deser.deserialize(p, ctxt);
                }
                continue;
            }
            if (_stdPropNames.localizedMessage.equalsIgnoreCase(propName)) {
                p.skipChildren();
                continue;
            }
            // Things marked as ignorable (or not in the "include" allow-list) should
            // not be passed to any setter. NOTE: checked only after the standard
            // `Throwable` properties above, so those are never dropped by the
            // ignore/include lists ([databind#6157]). They may still be excluded by an
            // explicit `@JsonView`, but that is decided by the branches above, not here.
            if (IgnorePropertiesUtil.shouldIgnore(propName, _ignorableProps, _includableProps)) {
                handleIgnoredProperty(p, ctxt, handledType(), propName);
                continue;
            }
            if (_anySetter != null) {
                // [databind#4316] Since 2.16.2 : at this point throwable should be non-null
                if (throwable == null) {
                    throwable = _instantiate(ctxt, hasStringCreator, null);
                }
                _anySetter.deserializeAndSet(p, ctxt, throwable, propName);
                continue;
            }

            // 23-Jan-2018, tatu: One concern would be `message`, but without any-setter or single-String-ctor
            //   (or explicit constructor). We could just ignore it but for now, let it fail
            // [databind#4071]: In case of "message", skip for default constructor
            if (_stdPropNames.message.equalsIgnoreCase(propName)) {
                p.skipChildren();
                continue;
            }

            // Unknown: let's call handler method
            handleUnknownProperty(p, ctxt, throwable, propName);
        }
        // Sanity check: did we find "message"?
        if (throwable == null) {
            throwable = _instantiate(ctxt, hasStringCreator, null);
        }

        // any pending values?
        if (pending != null) {
            for (int i = 0, len = pendingIx; i < len; i += 2) {
                SettableBeanProperty prop = (SettableBeanProperty)pending[i];
                Object value = pending[i+1];
                // Skip null values for properties that don't accept them
                if (value == null && _shouldSkipNullValue(prop.getName())) {
                    continue;
                }
                prop.set(ctxt, throwable, value);
            }
        }

        // any suppressed exceptions?
        if (suppressed != null) {
            for (Throwable s : suppressed) {
                // 13-Dec-2023, tatu: But skip any `null` entries we might have gotten
                if (s != null) {
                    throwable.addSuppressed(s);
                }
            }
        }

        return throwable;
    }