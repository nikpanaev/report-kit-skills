# Метрики и источники

Сначала договориться об authoritative source/формуле для каждого показателя. ER, ERR и ERV не взаимозаменяемы; views/reach denominator, followers/date и post/clip population клиентские. Название метрики не доказывает её формулу. Если нужное поле только в сводном UI, читать UI с exact period, не подменять похожим API полем.

Для каждого значения сохранить raw locator, account/network, requested period/filter, provider date/population, unit/denominator, calculation и rounding. Null/unknown/error не ноль. После pagination проверять actual from/to либо даты каждого item и source IDs. Post count и число уникальных снимков могут различаться.

Суммы, среднее/медиана, follower delta соседних verified endpoints, процентное изменение и процентные пункты проверять отдельно. Для previous0 percentage undefined, не Infinity/придуманный0. Коррекцию человеческой ошибки в принятой истории согласовать отдельно и сохранить prior snapshot.

Поздние counter values могут измениться; frozen rebuild и новый сбор разных timestamps не сравнивать как одинаковые inputs. Историю, которую владелец запретил пересобирать, не запрашивать. Coverage всего массива либо exact ограничение, не preview20items/full claim.
