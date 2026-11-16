# Ley 21.719: answers from the law itself

Spike #381, researched 2026-11-16. It answers the 14 [open legal questions](compliance-audit.md#open-legal-questions) of the readiness audit (#366) from the primary sources, proposes a decision for Rakin on each, and leaves the lawyer [five yes/no confirmations](#for-the-lawyer).

**This is research, not legal advice.** Every answer is a proposal. The owner approves the ones marked *approve it yourself*; the lawyer confirms the rest.

The text quoted is Ley 19.628 as Ley 21.719 rewrites it, in the consolidated version BCN publishes for 1 December 2026 (see [sources](#sources)). Article numbers are those of Ley 19.628 unless marked "21.719 transitorio".

## The table

Confidence: **clear** (clear in the text), **reasonable** (a reasonable reading of the text), **open** (the text is silent or ambiguous, or it depends on facts only the owner knows).

| # | Question | Proposed decision | Confidence | Who decides |
| --- | --- | --- | --- | --- |
| 1 | Consent age for minors | Keep 18 as the age at which a member is their own contact and payer (Código Civil). The data law's ages are 14 (general) and 16 (sensitive data); record a guardian's *consent* only where it is needed: under 14, and sensitive data under 16 | clear | approve it yourself |
| 2 | Is belt and attendance history profiling? | A coach's promotion is not. Attendance counts that flag people (inactive list, the v2 "ready for promotion" flag) are, on a broad reading. Say so in the notice; never let the app promote anyone by itself | reasonable | approve it yourself |
| 3 | First-year warnings only for small companies | Do not plan on it: the Agencia *may* warn instead of fining, only for 12 months, and the warning is published. Comply from the effective date | clear | approve it yourself |
| 4 | Effective date | 1 December 2026 is the law today. The Senate passed 15 October 2027 on 28 October; the bill is in the Cámara. Plan to 1 December and recheck before onboarding | clear | approve it yourself |
| 5 | Privacy notice wording | Already with the lawyer. The template lacks seven items of art. 14 ter; the list is [below](#5-privacy-notice-wording) for that review | clear | the lawyer (already pending) |
| 6 | Legal basis | Contract for adults and for 14 to 17 (signed by the guardian), not consent: `technical.md` is wrong. Children under 14 need the guardian's consent recorded, including those added by staff or import | reasonable; open for under-14s | **the lawyer (item 1)** |
| 7 | Accounting retention | Keep ledger entries, with name and RUT, for 6 years: a legal duty (Código Tributario arts. 17 and 200), so it survives a deletion request. Anonymise the rest | reasonable | **the lawyer (item 2)** |
| 8 | Retention promise | Drop "hasta que pidas que lo borremos": an open-ended period needs consent (art. 3 c). Anonymise a former student 24 months after their membership ends; let them opt in to keep their grade history | clear | approve it yourself |
| 9 | Subprocessors abroad | The DPA names each subprocessor and the gym authorises each in writing: the law says "específica". Each transfer rests on the provider's contractual clauses. The notice names the countries | reasonable; open whether provider clauses suffice | **the lawyer (item 3)** |
| 10 | Shared identity across gyms | Not a communication today: no gym learns anything. The risk is the company becoming *controller* of the shared table. Reduce `person` to the RUT and describe the link in the DPA | open | **the lawyer (item 4)** |
| 11 | Breach deadlines | The law sets no hours. The DPA sets them: company to gym within 24 hours, gym to Agencia within 72. Almost every Rakin breach must also be told to members, because it touches payment data | clear on who; open on hours | **the lawyer (item 3)** |
| 12 | Turning 18 | No new consent: the membership is the basis. At 18 the member takes over as contact and payer, with a fresh look at the notice | reasonable | approve it yourself |
| 13 | WhatsApp from staff phones | That sending is the gym's own processing, not the company's. The notice names WhatsApp (Meta, United States) as a channel the gym uses; the DPA says the sending is outside the service | reasonable | approve it yourself |
| 14 | Registration and a delegate | No registry exists for controllers or processors, and a delegate is voluntary | clear | approve it yourself |

One finding the audit did not ask about, and the most serious: **art. 16 bis bans health data collected "en el ámbito ... deportivo"** unless a law expressly allows it. Consent, which #376 planned to add, may not be enough. See [Health data in a gym](#found-along-the-way-health-data-in-a-gym), lawyer item 5.

## For the lawyer

Five confirmations, each a yes or no. The privacy notice wording is a separate, already pending review.

1. **Children under 14.** A membership is a contract (art. 13 c), but art. 16 quáter, inciso 2, requires the consent of "sus padres o representantes legales" to process a child's data "salvo que expresamente lo autorice o mandate la ley". We read the contract as *not* being that express authorisation, so we will record the guardian's consent for every member under 14, including those staff add by hand or import. For 14 to 17 we rely on the contract the guardian signs. Is that right?
2. **Ledger after a deletion request.** We keep each ledger entry (amount, date, method, the member's name and RUT) for 6 years, under Código Tributario arts. 17 and 200, as a legal obligation (art. 13 b; art. 7, inciso 2, ii), even after the member asks to be deleted, and anonymise everything else. Is 6 years the right period, and may the name and RUT stay for it?
3. **The DPA's shape.** (a) It names each subprocessor and its country, and the gym's signature is the "autorización específica y por escrito" art. 15 bis requires; a new subprocessor needs a new written authorisation from each gym. (b) Transfers to the United States rest on each provider's own contractual clauses (art. 27 b), since the Agencia has published no adequacy list and no model clauses. (c) The company tells the gym of a breach within 24 hours of knowing; the gym reports to the Agencia within 72 hours (art. 14 sexies says only "sin dilaciones indebidas"); the company drafts both and may send the members' notice in the gym's name. Is that shape right?
4. **One identity across gyms.** The company keeps one `person` row per RUT, shared by every gym that enrols that RUT. No gym learns anything from it. We will reduce that row to the RUT alone and describe the link in every gym's DPA as part of the service the gym instructs, so the company stays a processor (art. 15 bis, inciso 2). Does that keep the company a processor, with no disclosure owed beyond the DPA?
5. **Health data in a gym.** Art. 16 bis, final inciso, prohibits processing health data "recolectados en el ámbito laboral, educativo, deportivo ... salvo que la ley expresamente autorice su tratamiento". We read this as forbidding a gym to store injuries or medical conditions even with the member's consent, so Rakin will not offer health fields and will warn when a gym creates one. Is that right, and does it cover an emergency contact or a weight class (not health data, we think)?

## 1. Consent age for minors

**Answer.** Both numbers in the audit are in the text, for different things. Art. 16 quáter:

> "para tratar los datos personales de los niños y niñas se requiere el consentimiento otorgado por sus padres o representantes legales o por quien tiene a su cargo el cuidado personal del niño o niña, salvo que expresamente lo autorice o mandate la ley. Los datos personales de los adolescentes se podrán tratar de acuerdo a las normas de autorización previstas en esta ley para los adultos, salvo lo dispuesto en el inciso siguiente. Los datos personales sensibles de los adolescentes menores de dieciséis años sólo se podrán tratar con el consentimiento otorgado por sus padres [...]. Para los efectos de esta ley, se consideran niños o niñas a los menores de catorce años, y adolescentes, a los mayores de catorce y menores de dieciocho años."

So a guardian's consent is needed under 14, and for sensitive data under 16. From 14 a member's ordinary data is processed under the adults' rules. The same article requires "atendiendo al interés superior de éstos y al respeto de su autonomía progresiva" for everyone under 18.

The membership is another matter. Under the Código Civil, anyone under 18 is a *menor* (art. 26), and a *menor adulto* is relatively incapable (art. 1447): their contracts need their representative. So a guardian signs and pays for a 16-year-old's membership even though the data law treats that 16-year-old's data as an adult's.

**Proposed decision.** Keep `ADULT_AGE = 18` (`backend/app/schemas/join.py:25`) for who is the **contact and payer**: that is a contract rule, and stricter than the data law requires. Record the guardian's **consent** only where the data law needs it: under 14 always, and for sensitive data under 16 (if a gym may hold any, see [health data](#found-along-the-way-health-data-in-a-gym)). Nothing in the routing changes. #370 records which applies, #368 routes by age.

**Confidence:** clear. **Needs the lawyer:** no; the under-14 point is item 1 under [question 6](#6-legal-basis).

## 2. Profiling

**Answer.** Art. 2 w) defines *elaboración de perfiles* broadly:

> "toda forma de tratamiento automatizado de datos personales que consista en utilizar esos datos para evaluar, analizar o predecir aspectos relativos al rendimiento profesional, situación económica, de salud, preferencias personales, intereses, fiabilidad, comportamiento, ubicación o movimientos de una persona natural."

A belt history is a record of a coach's decision, not an automated evaluation. But the app does count attendance to flag people: the inactive list, and the v2 "ready for promotion" flag (`GoalMetric`, `backend/app/schemas/grading.py:26`). On a broad reading that is evaluating behaviour automatically.

What follows from it is small:

- The right to object to automated decisions applies to decisions "basadas en el tratamiento automatizado [...] que produzca efectos jurídicos en él o le afecte significativamente" (art. 8 bis). A coach decides every promotion, so it does not apply.
- The notice must state "La existencia de decisiones automatizadas, incluida la elaboración de perfiles" (art. 14 ter l).
- An impact assessment is mandatory only for "Evaluación sistemática y exhaustiva [...] que produzcan en ellos efectos jurídicos significativos" (art. 15 ter a). Counting classes is neither.
- For children, the "interés superior" of art. 16 quáter applies throughout.

**Proposed decision.** One sentence in the notice template: the app counts attendance to show staff who has stopped coming or is close to a grade, and a person makes every decision. Never let the app promote anyone, or change a membership, by itself.

**Confidence:** reasonable. **Needs the lawyer:** no; the sentence goes in with the notice review.

## 3. Small companies

**Answer.** 21.719 transitorio, art. 6:

> "Durante los primeros doce meses luego de la entrada en vigencia de esta ley, en los casos en que proceda alguna sanción para empresas calificadas como de menor tamaño, de acuerdo a las categorías establecidas en el artículo segundo de la ley N° 20.416 [...], la Agencia **podrá** aplicar como sanción una amonestación por escrito [...]. A esta amonestación será aplicable el deber de registro según lo dispone el artículo 39".

Ley 20.416, art. 2, counts as *de menor tamaño* a company with annual sales up to 100,000 UF (micro up to 2,400, small up to 25,000, medium up to 100,000). A gym, and a company of Rakin's size, very likely fall inside it; the owner knows the company's figures.

Three limits:

- It is discretionary ("podrá"), not a right.
- It lasts twelve months from the effective date.
- The warning is published in the Registro Nacional de Sanciones y Cumplimiento (art. 39) for five years.

It does nothing about civil damages (art. 47) or what the company owes a gym under contract.

A related point the text leaves unclear: the sanctions title is written for the *responsable* (arts. 33, 34). A processor is treated as one when it processes "con un objeto distinto del encargo convenido" (art. 15 bis, inciso 2). Art. 15 bis also binds it to the secrecy and security duties (arts. 14 bis, 14 quinquies). Whether the Agencia can fine a processor directly for a security failure is not spelled out.

**Proposed decision.** Do not plan on the warning. Treat the effective date as the date to comply.

**Confidence:** clear (that it is discretionary and short). **Needs the lawyer:** no.

## 4. Effective date

**Answer.** 21.719 transitorio, art. 1: the amendments take effect "el día primero del mes vigésimo cuarto posterior a la publicación de esta ley en el Diario Oficial". It was published on 13 December 2024, so the date is **1 December 2026**.

The postponement bill, **boletín 18.623-07**, replaces that phrase with "15 de octubre de 2027". It also grows the Agencia's council from three to five members and rewrites how the first one is appointed (oficio 355/SEC/26, 28 October 2026). Its stage, from the Senado's tramitación record on 16 November 2026:

- 1 September 2026: filed in the Senado.
- 28 October 2026: approved by the Senado in general and in particular.
- 2 November 2026: received by the Cámara, sent to the Constitución committee.
- 10 November 2026: Constitución's report; sent to Hacienda.
- 11 November 2026: urgency *discusión inmediata* renewed.

It is not law yet. It still needs the Cámara's vote, promulgation and publication. If it is published after 1 December, the law will already be in force for some days, and what the bill then does is a question for the lawyer. It changes nothing in this plan.

The Agencia does not exist in practice yet. The Senado rejected the first proposed council on 19 May 2026 for lack of the two-thirds quorum (Senado news), and the bill's new appointment rules start from that rejection. I found no regulation, instruction, model contract or adequacy list from the Agencia.

**Proposed decision.** Plan to 1 December 2026. The four blockers in the audit stand whatever the date. Recheck the bill before onboarding a second gym.

**Confidence:** clear (the current date). **Needs the lawyer:** no.

## 5. Privacy notice wording

The wording is with the owner's lawyer and out of scope here. For that review, these are art. 14 ter's items checked against the template (`frontend/src/i18n/es.ts`, `privacy`):

| Art. 14 ter | Required | In the template |
| --- | --- | --- |
| a) | the policy, "la fecha y versión de la misma" | a date; no version |
| b) | the controller "y su representante legal" | legal name and RUT; no legal representative |
| c) | an address or email for requests | yes |
| d) | data categories, "la descripción genérica del universo de personas", recipients, purposes, legal basis, and which legitimate interests | no universe (members, guardians, staff); no legitimate interest named, though the inactive nudges may rest on one |
| e) | "La política y las medidas de seguridad adoptadas" | **missing** |
| f) | the rights | yes |
| g) | the right to complain to the Agencia | yes |
| h) | transfer abroad, "y si éstos ofrecen o no un nivel adecuado de protección", and the guarantees | "fuera de Chile, con medidas de seguridad adecuadas": no country, no adequacy statement |
| i) | "El periodo durante el que se conservarán los datos" | "el plazo que exige la ley" and "hasta que pidas": no period ([question 8](#8-retention-promise)) |
| j) | "La fuente de la cual provienen los datos" | **missing** (the member, their guardian, or the gym's staff) |
| k) | where the basis is consent, the right to withdraw it | **missing** for minors' guardians |
| l) | automated decisions, including profiling | **missing** ([question 2](#2-profiling)) |

Failing art. 14 ter is a *leve* infraction (art. 34 bis a) for the gym, the controller.

**Proposed decision.** Send this table to the lawyer with the wording review. Once the wording returns, the template change is its own issue.

**Confidence:** clear. **Needs the lawyer:** yes, already pending.

## 6. Legal basis

**Answer.** Consent is one basis among several (art. 12). Art. 13 c) allows processing without consent "Cuando el tratamiento de datos sea necesario para la celebración o ejecución de un contrato entre el titular y el responsable". And art. 12 warns against asking for consent where a contract already covers the processing:

> "Se presume que el consentimiento para tratar datos no ha sido libremente otorgado cuando el responsable lo recaba en el marco de la ejecución de un contrato o la prestación de un servicio en que no es necesario efectuar esa recolección."

So for adults the notice is right (contract) and `technical.md` is wrong ("consent captured at membership creation (adult)"). A member added by staff or by import is in the same position: the membership is the contract. The duty to inform is public and general (art. 14 ter: "mantener permanentemente a disposición del público, en su sitio web"), so the gym's `/privacidad` meets it for everyone. Telling the source of the data (14 ter j) covers the members who never filled in the form.

Some uses go beyond the contract and need their own basis. The inactive nudges are the gym's legitimate interest (art. 13 d), and the notice must name that interest (art. 14 ter d). Health data is a different question again (see below).

For **children under 14**, art. 16 quáter requires the guardian's consent "salvo que expresamente lo autorice o mandate la ley". Art. 13 c) is a law that authorises processing for a contract. If it counted as that express authorisation, the children's rule would mean nothing. The reasonable reading is that it does not, so a child's guardian must consent, and the gym must be able to prove it (art. 12, last inciso: "Corresponde al responsable probar que contó con el consentimiento del titular"). For **14 to 17**, the adults' rules apply (contract), signed by the guardian.

**Proposed decision.**

- `technical.md`: for adults and members of 14 to 17 the basis is the membership contract. For under-14s it is the guardian's consent, recorded with the notice version.
- #370: record the basis per member. For every member under 14, *including staff-added and imported*, record the guardian's consent with its timestamp and notice version: send the guardian a link to give it. Adults need no consent record. Keep the join form's timestamp as evidence that the notice was shown.

**Confidence:** reasonable for adults; open for under-14s added by staff. **Needs the lawyer:** yes, [item 1](#for-the-lawyer).

## 7. Accounting retention

**Answer.** The duty is the gym's, as a taxpayer. Código Tributario art. 17, inciso 1: the books "deberán ser conservados por los contribuyentes, junto con la documentación correspondiente, mientras esté pendiente el plazo que tiene el Servicio para la revisión de las declaraciones". Art. 200 sets that period at "tres años contado desde la expiración del plazo legal en que debió efectuarse el pago", and "seis años [...] cuando ésta no se hubiere presentado o la presentada fuere maliciosamente falsa". A gym cannot know in advance which applies, so 6 years is the safe figure.

The tax law asks for the books and their supporting documents, not specifically for the customer's name (a boleta does not carry it). But a ledger entry without a name cannot be checked against a transfer or a dispute. Separately, the ordinary civil action lasts five years (Código Civil art. 2515), which covers a claim over a payment.

On the data side, this is a **legal duty**, not a legitimate interest. Art. 13 b) covers processing "necesario para la ejecución o el cumplimiento de una obligación legal". Art. 7 refuses deletion when processing is necessary "Para el cumplimiento de una obligación legal o la ejecución de un contrato" (ii) or "Para la formulación, ejercicio o defensa de una reclamación administrativa o judicial" (vi). Art. 3 c) allows keeping data longer than the purpose "sin perjuicio de las excepciones que establezca la ley".

**Proposed decision.**

- On a deletion request from a member who paid (#372), keep the ledger entries with name and RUT for 6 years after the year they belong to, marked as kept for tax, and anonymise everything else.
- After 6 years, anonymise the entries too (#378).
- Proofs are not the gym's accounting documents (the bank statement is): delete them as #378 plans.
- The notice says "6 años, por obligación tributaria".

**Confidence:** reasonable (6 years is the upper bound; the text does not say the name must be kept). **Needs the lawyer:** yes, [item 2](#for-the-lawyer).

## 8. Retention promise

**Answer.** Art. 3 c):

> "Los datos personales pueden ser conservados sólo por el período de tiempo que sea necesario para cumplir con los fines del tratamiento, luego de lo cual deben ser suprimidos o anonimizados, sin perjuicio de las excepciones que establezca la ley. Un período de tiempo mayor requiere autorización legal o consentimiento del titular."

The notice must state the period (art. 14 ter i). "Hasta que pidas que lo borremos" is no period at all. It keeps a former student's data indefinitely on a contract that has ended, and would need their consent.

How long is "necessary" after a student leaves is the gym's call: students come back, and a returning student's belt matters to them. 24 months is defensible.

**Proposed decision.**

- Anonymise a former student 24 months after their last membership ends, except the ledger for the tax period ([question 7](#7-accounting-retention)).
- Offer an opt-in, on leaving or later, to keep their grade history longer. That is consent: revocable, and recorded.
- The notice states both; `technical.md` already says 24 months.
- Code: #378. Text: with the notice review.

**Confidence:** clear (an open-ended period needs consent); the 24 months is the owner's choice. **Needs the lawyer:** no.

## 9. Subprocessors abroad

**Answer.** Two rules apply.

**Delegation.** Art. 15 bis:

> "El encargado no podrá delegar parte o la totalidad del encargo, salvo que conste una autorización **específica y por escrito** del responsable. El encargado que delegue a otro encargado parte o la totalidad del encargo, continuará siendo solidariamente responsable sobre dicho encargo".

The same article lists the contract's contents: "el objeto del encargo, la duración del mismo, la finalidad del tratamiento, el tipo de datos personales tratados, las categorías de titulares [...] y los derechos y obligaciones de las partes". The GDPR allows a *general* written authorisation for subprocessors. This text says *specific*, so a blanket clause is the weaker reading.

**Transfer abroad.** Art. 27 allows a habitual transfer on one of three grounds:

- (a) a country the Agencia declares adequate (art. 28);
- (b) "cláusulas contractuales, normas corporativas vinculantes, u otros instrumentos jurídicos [...] y en ellas se establezcan garantías adecuadas";
- (c) a certified compliance model.

The exceptions after it (express consent, contract necessity) are only for "una transferencia específica y que no sea habitual", which ours is not.

Adequate guarantees are those that "otorguen derechos exigibles y acciones legales efectivas a los titulares de los datos" (art. 28). The Agencia may approve model clauses and will publish a list of adequate countries. It has published neither (see [question 4](#4-effective-date)).

**The notice.** Art. 14 ter h) asks for the country and whether it is adequate. Art. 14 ter d) asks only for recipients, which categories satisfy. Art. 5 c) gives the member the right to "la identidad de cada destinatario" on request.

**Proposed decision.**

- #367: the DPA's annex names every subprocessor (VPS host, Cloudflare R2, Resend, Sentry, Turnstile where on), what it does, the data it gets, and its country. The gym's signature is the specific written authorisation. Adding or replacing one needs a signed annex update from each gym, with a right to leave.
- Each transfer rests on the provider's own data processing terms and contractual clauses, recorded in the annex.
- The notice names the countries (United States; Brazil if the VPS is in São Paulo) and says no adequacy decision exists yet, with the guarantee relied on.
- #373: sending Sentry less data reduces what crosses.

**Confidence:** reasonable on "específica"; open on whether the providers' clauses count as adequate guarantees before the Agencia approves any. **Needs the lawyer:** yes, [item 3](#for-the-lawyer).

## 10. Shared identity

**Answer.** A *comunicación* is "dar a conocer [...] datos personales a personas distintas del titular" (art. 2 c). A *cesión* is a transfer to another controller (art. 2 v).

In the code, `join_gym` (migration 0036) writes gym B's record with what gym B entered, and it answers the same whether the RUT was new or known. The `person` row keeps the first gym's name, email and birth date, but no gym reads it. So nothing is made known to gym B: today this is neither a communication nor a cesión.

The risk is elsewhere. The `person` table serves every gym at once, for a purpose (one identity across gyms, the v2 badge and visits, #182's merges) that no single gym instructed. A processor that processes "con un objeto distinto del encargo convenido" is "considerado como responsable de datos para todos los efectos legales" (art. 15 bis, inciso 2). If the shared table is the company's own purpose, the company is its controller, with every controller duty.

**Proposed decision.**

- Reduce `person` to `id` and `rut` (#372 already suggests it), so no gym's other data sits outside its own tenancy.
- Describe the link in every gym's DPA as part of the service the gym instructs: "identificar a la persona por su RUT en el servicio Rakin, sin revelar nada a otras academias".
- Anything that would show one gym a member's activity at another (the v2 badge and visits, a merge in #182) is a communication: it waits for the member's consent and its own design.

**Confidence:** open. **Needs the lawyer:** yes, [item 4](#for-the-lawyer).

## 11. Breach notice

**Answer.**

- **Processor to controller.** Art. 15 bis: "Tratándose de una vulneración a las medidas de seguridad, el tercero o mandatario deberá reportar este hecho al responsable." No deadline.
- **Controller to the Agencia.** Art. 14 sexies: "por los medios más expeditos posibles y sin dilaciones indebidas", for breaches "cuando exista un riesgo razonable para los derechos y libertades de los titulares". Every such report must also be recorded: nature, effects, data categories, approximate number of people, measures taken.
- **Controller to members.** Art. 14 sexies, inciso 3: required when the breach concerns "datos personales sensibles, datos relativos a niños y niñas menores de catorce años o datos relativos a obligaciones de carácter económico, financiero, bancario o comercial". The notice goes to each member, through their representative where there is one; if that is impossible, by a notice in national media.

Rakin holds every member's dues, payments and overdue amounts, which on a reasonable reading are commercial obligations, and many under-14s. So almost every breach of Rakin is one the members must be told about.

The duty is the controller's, so the gym notifies. The company can prepare and send the notice in the gym's name if the DPA says so, but the gym stays liable. Omitting the report or the record is *grave* (art. 34 ter k); omitting it deliberately is *gravísima* (art. 34 quáter f).

**Proposed decision.** The runbook (#369) and the DPA (#367) set what the law leaves open:

- the company tells the gym within 24 hours of knowing, with what it knows, and updates as it learns;
- the company drafts the Agencia report and the members' notice;
- the gym reports to the Agencia within 72 hours (a common reading of "sin dilaciones indebidas", from the GDPR);
- the company sends the members' notice in the gym's name unless the gym prefers to;
- every incident is recorded, notified or not (#374 makes that possible).

**Confidence:** clear on who and what; open on the hours. **Needs the lawyer:** yes, [item 3](#for-the-lawyer).

## 12. Turning 18

**Answer.** The data law has no rule for it. Its thresholds are 14 (adults' rules apply) and 16 (sensitive data) (art. 16 quáter). At 18, *patria potestad* ends (Código Civil art. 270, 4°) and with it the guardian's legal representation (art. 43). Consent, where there was any, stays revocable by the person themselves at any time (art. 12).

What holds the record past 18 is the membership contract (art. 13 c), not the guardian's consent. The only consent-based data, a child's under 14, already moved to the contract basis at 14.

**Proposed decision.** No new consent at 18.

- At 18 the member becomes the contact and payer: Rakin asks them to confirm their own email and phone and shows them the notice.
- The guardian link ends, unless the member keeps the guardian as payer.
- At 16, if the gym holds any sensitive field for them, ask the member's own consent ([question 1](#1-consent-age-for-minors)).

Routing by age is #368's.

**Confidence:** reasonable (the text is silent on a lapse). **Needs the lawyer:** no.

## 13. WhatsApp from staff phones

**Answer.** Rakin builds a `wa.me` link (`frontend/src/components/ReminderLink.tsx`). The coach taps it, and the message goes from the coach's own WhatsApp, on their own phone. From that moment the number and the text are outside Rakin's servers, handled by the gym's staff and by WhatsApp (Meta, in the United States).

The gym decides that purpose and that means, so it is the gym's own processing as controller. The company only built a link. The gym "debe adoptar las medidas necesarias con el objeto que sus dependientes [...] cumplan el deber de secreto" (art. 14 bis). The notice must name the recipients and any transfer abroad (art. 14 ter d, h).

**Proposed decision.**

- The notice template names WhatsApp, run by Meta in the United States, as a channel the academy uses from its staff's phones.
- The DPA (#367) says that sending through `wa.me` is the gym's own processing, outside the service.
- Rakin keeps doing what it does: no link with WhatsApp off or no phone, and a minor's goes to their guardian.

**Confidence:** reasonable. **Needs the lawyer:** no.

## 14. Registration and a delegate

**Answer.**

- **No registry.** The only registry the old law had, for public bodies' databases (old art. 22), is abolished: "el Servicio de Registro Civil e Identificación deberá eliminar el registro de los bancos de datos personales" (21.719 transitorio, art. 3). The new Registro Nacional de Sanciones y Cumplimiento (art. 39) records sanctions and certified compliance models, nothing else.
- **A delegate is voluntary.** "El responsable de datos **podrá** designar un delegado" (art. 50). It belongs to the voluntary compliance model of art. 49, and "En las micro, pequeñas y medianas empresas, el dueño o sus máximas autoridades podrán asumir personalmente las tareas de delegado".
- **Foreign companies.** Only a controller not established in Chile must name a contact before the Agencia (arts. 10 and 14). A certified model is a mitigating circumstance (art. 36, 5).

**Proposed decision.** No registration and no delegate. The owner is the named contact for data protection in the DPA and the runbook. Revisit a certified compliance model once the Agencia certifies any.

**Confidence:** clear. **Needs the lawyer:** no.

## Found along the way: health data in a gym

The audit treated health fields (weight, injuries, conditions) as sensitive data that needs explicit consent (#376). Art. 16 bis goes further. Its first inciso says that even with the explicit consent of art. 16, health data "sólo podrán ser tratados para los fines previstos por las leyes especiales en materia sanitaria". Its final inciso:

> "Se prohíbe el tratamiento y la cesión de los datos relativos a la salud y al perfil biológico de un titular [...] cuando los datos o muestras han sido recolectados en el ámbito laboral, educativo, **deportivo**, social, de seguros, de seguridad o identificación, salvo que la ley expresamente autorice su tratamiento en casos calificados".

The exceptions do not cover a gym's file on injuries. The closest is "indispensable para salvaguardar la vida o integridad física", and it reads as a rule for the emergency itself, not for keeping a list in advance. A breach of this rule can be *gravísima* (art. 34 quáter e, "a sabiendas").

An emergency contact is not health data. A weight kept for weight classes is a physical characteristic; whether it "revela" health (art. 2 g) is arguable.

**Proposed decision, until the lawyer answers.**

- Rakin does not suggest health fields: no "lesiones" in examples or presets.
- It warns an owner who creates a sensitive field.
- #376's per-gym switch defaults to off.
- Free-text reasons and notes (a freeze for "lesión") get a hint not to record health details.

**Confidence:** open. **Needs the lawyer:** yes, [item 5](#for-the-lawyer).

## What changes in the gap issues

| Issue | Change |
| --- | --- |
| #367 DPA | contents of art. 15 bis; subprocessors authorised one by one; transfer clauses; breach hours; shared identity and `wa.me` described (questions 9, 10, 11, 13) |
| #368 minors | route by age: contact and payer under 18; consent rules at 14 and 16 (questions 1, 12) |
| #369 breach runbook | the three notification paths of art. 14 sexies and the hours above; members are told about almost every breach (question 11) |
| #370 consent record | basis per member; guardian consent recorded for every under-14, including staff-added and imported; none needed for adults (question 6) |
| #371 view and export | access (art. 5) is owed to everyone, free at least quarterly (art. 10); portability (art. 9) only where the basis is consent, so mainly under-14s. The JSON export still serves both |
| #372 deletion | refusal is lawful while the contract runs (art. 7 ii); afterwards, keep the ledger for 6 years and anonymise the rest; reduce `person` to the RUT (questions 7, 10) |
| #373 Sentry | it is a transfer abroad under art. 27: less data, and the provider's clauses in the DPA annex |
| #374 incident logs | art. 14 sexies requires a record of every breach: nature, effects, categories, number of people, measures |
| #375 request to the company | the controller answers within 30 calendar days, extendable once by 30 (art. 11); the company forwards at once |
| #376 sensitive fields | art. 16 bis may forbid health data in a gym even with consent; the switch defaults to off (lawyer item 5) |
| #377 offboarding | at the end of the service the processor must delete or return the data (art. 15 bis, last inciso) |
| #378 retention | fixed periods: 24 months after a membership ends, 6 years for the ledger, an opt-in to keep grade history (questions 7, 8) |

## Sources

All read on 2026-11-16.

**Primary**

- Ley 19.628, as amended by Ley 21.719, consolidated version in force from 2026-12-01 (BCN LeyChile, `idNorma=141599`): <https://www.bcn.cl/leychile/navegar?idNorma=141599&idVersion=2026-12-01>. Full text read through LeyChile's XML service: <https://www.leychile.cl/Consulta/obtxml?opt=7&idNorma=141599&idVersion=2026-12-01>
- Ley 21.719, including its transitory articles (BCN LeyChile, `idNorma=1209272`, version of 2026-02-05): <https://www.bcn.cl/leychile/navegar?idNorma=1209272>
- Boletín 18.623-07, the postponement bill, tramitación record from the Senado: <https://tramitacion.senado.cl/wspublico/tramitacion.php?boletin=18623>
- Oficio 355/SEC/26 of the Senado to the Cámara, 28 October 2026, with the text approved: <https://tramitacion.senado.cl/appsenado/index.php?mo=tramitacion&ac=getDocto&iddocto=37381&tipodoc=ofic>
- Senado, "Desestiman propuesta de consejeros para la Agencia de Protección de Datos Personales": <https://www.senado.cl/comunicaciones/noticias/desestiman-propuesta-de-consejeros-para-la-agencia-de-proteccion-de-datos>
- Ministerio de Economía, "Gobierno propone ampliar plazo para implementar nueva Ley de Protección de Datos y institucionalidad", September 2026: <https://www.economia.gob.cl/2026/09/01/gobierno-propone-ampliar-plazo-para-implementar-nueva-ley-de-proteccion-de-datos-y-institucionalidad.htm>
- Código Tributario, arts. 17 and 200 (BCN LeyChile, `idNorma=6374`, version of 2026-10-17): <https://www.bcn.cl/leychile/navegar?idNorma=6374>
- Código Civil, arts. 26, 43, 270, 1447 and 2515 (BCN LeyChile, `idNorma=172986`): <https://www.bcn.cl/leychile/navegar?idNorma=172986>
- Ley 20.416, art. 2 (BCN LeyChile, `idNorma=1010668`): <https://www.bcn.cl/leychile/navegar?idNorma=1010668>

**Not found.** The Agencia de Protección de Datos Personales has no website, regulation, instruction, model contract or adequacy list that I could find. Its council has not been appointed (above).

**Secondary, used only to find the primary texts**

- Carey, on the postponement bill: <https://www.carey.cl/gobierno-ingresa-proyecto-de-ley-que-posterga-en-un-ano-entrada-en-vigor-de-la-ley-sobre-proteccion-de-datos-personales>
- BCN, Balance legislativo of Ley 21.719: <https://www.bcn.cl/balance-legislativo/detalle/ficha_LEY_21719_2024-12-13>

Not consulted: Ley 19.496 (consumer law). No question needed it; Ley 21.719 only repeals its art. 15 bis.
