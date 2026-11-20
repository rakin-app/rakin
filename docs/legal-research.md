# Ley 21.719: answers from the law itself

Spike #381, researched 2026-11-16. It answers the 14 [open legal questions](compliance-audit.md#open-legal-questions) of the readiness audit (#366) from the primary sources, proposes a decision for Rakin on each, and leaves the lawyer [five yes/no confirmations](#for-the-lawyer).

Drafts built on these answers (the DPA, both privacy notices and the beta terms of service) are in [`docs/legal/`](legal/README.md).

A second spike, #500 (2026-11-20), asks whether accepting the terms in the app is valid: [Spike #500](#spike-500-accepting-the-terms-in-the-app).

**This is research, not legal advice.** Every answer is a proposal. The owner approves the ones marked *approve it yourself*; the lawyer confirms the rest.

The text quoted is Ley 19.628 as Ley 21.719 rewrites it, in the consolidated version BCN publishes for 1 December 2026 (see [sources](#sources)). Article numbers are those of Ley 19.628 unless marked "21.719 transitorio".

## The table

Confidence: **clear** (clear in the text), **reasonable** (a reasonable reading of the text), **open** (the text is silent or ambiguous, or it depends on facts only the owner knows).

| # | Question | Proposed decision | Confidence | Who decides |
| --- | --- | --- | --- | --- |
| 1 | Consent age for minors | **Decided 2026-11-16: conservative.** Every member under 18 needs their guardian's consent to the processing of their data, recorded as its own act apart from the membership, which the guardian can refuse or withdraw without losing it. 18 stays the age at which a member is their own contact and payer (Código Civil), so the app has one rule for minors. The data law's own ages are 14 (general) and 16 (sensitive data); this goes further | clear | decided by the owner |
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

One finding the audit did not ask about, and the most serious: **art. 16 bis bans health data collected "en el ámbito ... deportivo"** unless a law expressly allows it. Consent, which #376 planned to add, may not be enough. See [Health data in a gym](#found-along-the-way-health-data-in-a-gym), lawyer item 5, and #384.

## For the lawyer

Five confirmations, each a yes or no. The privacy notice wording is a separate, already pending review.

1. **Members under 18.** A membership is a contract (art. 13 c), but art. 16 quáter, inciso 2, requires the consent of "sus padres o representantes legales" to process a child's data "salvo que expresamente lo autorice o mandate la ley". We read the contract as *not* being that express authorisation. The law asks it under 14; the owner chose to go further (row 1), so we will record the guardian's consent for every member under 18, including those staff add by hand or import. Art. 12 also presumes that consent "no ha sido libremente otorgado" when it is collected "en el marco de la ejecución de un contrato" that does not need it, and here the guardian would give it while enrolling the child. So we would ask for it as a separate act from the membership: its own step, which the guardian can refuse or withdraw without losing the membership. Is that right, and is a separate act what art. 12 requires?
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
- #370: record the basis per member. For every member under 14, *including staff-added and imported*, record the guardian's consent with its timestamp and notice version: send the guardian a link to give it. Ask for it as its own step, apart from the membership, so it is not presumed unfree under art. 12; refusing or withdrawing it does not end the membership. Adults need no consent record. Keep the join form's timestamp as evidence that the notice was shown.

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
- The notice names the countries (the United States: the VPS is Hetzner in Ashburn, Virginia, and Sentry is on its US region, #430) and says no adequacy decision exists yet, with the guarantee relied on.
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

Rakin collects health data today: the "Lesión" and "Salud" freeze reasons, the "Lesión" chip for why someone left, and the seed's "Notas médicas" field. So this is its own issue, #384, labelled `blocks second gym`.

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
| #376 sensitive fields | art. 16 bis may forbid health data in a gym even with consent; the switch defaults to off (lawyer item 5). The gap is its own issue, #384 |
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

Not consulted for #381: Ley 19.496 (consumer law). No question needed it; Ley 21.719 only repeals its art. 15 bis. #500 reads it, [below](#4-the-consumer-law).

## Spike #500: accepting the terms in the app

Researched 2026-11-20. #499 replaces the signed PDF with acceptance in the app: the operator creates a gym with its owner's email, the owner signs in through a link or code sent to it, and accepts the Términos de servicio and the Términos de encargo with a checkbox and a button. This part asks whether that is a valid way to conclude both contracts in Chile, and what the flow and the texts must add. Same format and the same caveat as above: research, not legal advice.

**The short answer.** Yes, on the text of the law, with a better record than #499 sketches and a copy sent to the owner's email. The claim to check, that Chilean law accepts an email address as valid identification, is **half right**. No law names an email address, or any other means, as identification for this. What Ley 19.799 does is define a *firma electrónica* so broadly ("cualquier [...] proceso electrónico, que permite al receptor [...] identificar al menos formalmente a su autor") that a click by someone signed in through their inbox is one. The email is not what makes the acceptance valid: it is how Rakin proves who accepted, and that proof is weighed by a judge under the general rules. I found no court ruling, and no act of a regulator, on email-based identification either way.

### The table

| # | Question | Proposed decision | Confidence | Who decides |
| --- | --- | --- | --- | --- |
| 1 | Is the click a *firma electrónica*, with paper's validity? | Yes: a simple electronic signature (art. 2 f), so both contracts are valid as if signed on paper and count as written (art. 3). None of art. 3's three exceptions applies | clear | approve it yourself |
| 2 | Is control of the inbox enough to attribute it? | Enough to form the contract; its weight as proof is the judge's (art. 5, last inciso). Make the record strong: the address, the sign-in, the time, the versions, the hash, the IP and user agent of the acceptance only, and the copy sent | reasonable | approve it yourself |
| 3 | Ley 21.719's form for the processor contract | Art. 15 bis asks for a *contrato* with set contents, and "por escrito" only for the authorisation to subcontract. An electronic acceptance is "escrito" (Ley 19.799 art. 3). The authorisation must name each subprocessor on the page | reasonable | **the lawyer (item A)** |
| 4 | Ley 19.496 for a sole-trader gym | Not today: the beta is free, and the consumer law needs a price. Once Rakin charges, Ley 20.416 applies its rules to every micro or small gym, sole trader or company. Build art. 12 A now: the terms before accepting, savable and printable; a full copy by email after | clear (not today); reasonable (later) | **the lawyer (item C)**, before charging |
| 5 | A line in the texts | One clause, the same in both texts, and an acceptance block where the signature table is. Wording [below](#5-a-line-in-the-texts) | reasonable | the lawyer, with the texts' review |
| 6 | Re-accepting a new version | Same flow, but silence never accepts: the old version governs until the owner accepts or leaves. A new subprocessor is named on the page and authorised by name, and the company does not use it for a gym's data before that gym accepts | clear | approve it yourself |

Found along the way: **who clicks must be able to bind the gym.** For a gym run by a company, the titular accepts in its name, which binds it only if they may represent it (Código Civil art. 1448). See lawyer item B.

### For the lawyer

Three confirmations, each a yes or no.

- **A. The click as a written authorisation.** The owner, signed in through a link or code sent to their email, ticks a box and presses a button. We read this as a *firma electrónica* simple (Ley 19.799 art. 2 f) that makes the Términos de encargo valid and "escritos" (art. 3), including the "autorización específica y por escrito" to subcontract that Ley 19.628 art. 15 bis requires, because the page names each subprocessor. Is that right, or does that authorisation need more than a simple electronic signature?
- **B. Representation.** For a gym that is a company, the person who accepts declares, in the checkbox's own words, that they may represent it. We record their name and that declaration, and do not check a power of attorney. Is a declaration enough for a beta among known gyms, or should the operator see the company's representation (an extract from the Registro de Empresas y Sociedades, or the *escritura*) before creating it?
- **C. When Rakin charges.** Through Ley 20.416, art. 9, a micro or small gym gets the consumer law's rules against its providers. We read that as bringing in, once there is a price: the right to cancel within 10 days of an electronic contract unless the terms exclude it beforehand, prominently (Ley 19.496 art. 3 bis b); the right to go to its own court, and to the *juzgado de policía local* where the contract was made (art. 3 g; Ley 20.416 art. 9, 4); and the rules on adhesion contracts (arts. 16 and 17). Is that right, and does it make section 11's choice of a single city's courts ineffective against those gyms?

### 1. Is the click a firma electrónica

**Answer.** Ley 19.799, art. 2:

> "f) Firma electrónica: cualquier sonido, símbolo o proceso electrónico, que permite al receptor de un documento electrónico identificar al menos formalmente a su autor;"
>
> "d) Documento electrónico: toda representación de un hecho, imagen o idea que sea creada, enviada, comunicada o recibida por medios electrónicos y almacenada de un modo idóneo para permitir su uso posterior;"

The *firma electrónica avanzada* (art. 2 g) is the other kind: certified by an accredited provider who checked the signer in person (art. 12 e). #499's flow is not that, and does not need to be. Art. 3:

> "Los actos y contratos otorgados o celebrados por personas naturales o jurídicas, suscritos por medio de firma electrónica, serán válidos de la misma manera y producirán los mismos efectos que los celebrados por escrito y en soporte de papel. Dichos actos y contratos se reputarán como escritos, en los casos en que la ley exija que los mismos consten de ese modo [...]."
>
> "La firma electrónica, cualquiera sea su naturaleza, se mirará como firma manuscrita para todos los efectos legales [...]."

"Cualquiera sea su naturaleza": the simple signature has the same legal effect as the advanced one. The advanced one is required only for public instruments (art. 4), which these are not.

The exceptions in art. 3 are acts that need "una solemnidad que no sea susceptible de cumplirse mediante documento electrónico", acts that need "la concurrencia personal de alguna de las partes", and those "relativos al derecho de familia". A service contract and a processing contract need none of these: neither Ley 19.628 nor any other law I found makes them solemn or asks for the parties in person.

The principle of art. 1, "equivalencia del soporte electrónico al soporte de papel", governs how all of this is read.

**Proposed decision.** The acceptance in #499 is a simple electronic signature, and it concludes both contracts with the validity of a signed paper copy. The company needs no certification provider and no advanced signature for it.

**Confidence:** clear. **Needs the lawyer:** no; item A asks only about the art. 15 bis authorisation.

### 2. Identification

**Answer.** The law asks of a simple signature only that it let the receiver identify its author "al menos formalmente" (art. 2 f). It names no method, and no regulation does: the Subsecretaría de Economía, the Entidad Acreditadora (art. 2 e), regulates certification providers and advanced signatures (Title III onward), not how a simple signature identifies its author. So no rule makes an email address valid identification, and none forbids it.

Whether it is enough is a question of proof, not of validity. Art. 5, last inciso:

> "En el caso de documentos electrónicos que posean la calidad de instrumento privado y estén suscritos mediante firma electrónica, tendrán el valor probatorio que corresponda, de acuerdo a las reglas generales."

An advanced signature would be full proof (art. 5, 2); a simple one is weighed. If the gym denies it accepted, the company presents the record in court; the court holds a hearing to see it, and if the gym objects, may order an expert test of its authenticity (Código de Procedimiento Civil art. 348 bis). Being "escrito" also matters for proof: a contract worth more than two UTM must be in writing, and testimony cannot replace it (Código Civil arts. 1708 and 1709). Through art. 3 of Ley 19.799, the electronic record is that writing.

So the record has one job: to make it hard to deny that the owner, in person, accepted that exact text. What attributes it to them is a chain, and each link should be recorded:

1. the owner gave the operator their email, and the operator created the gym with it (#499 step 1);
2. a link or code was sent to that address, and was used from a browser within 15 minutes, once (`LINK_TTL` in `backend/app/magiclink/service.py`);
3. the session that link started, which remembers the address it signed in with, is the one that accepted;
4. the acceptance was of a text whose SHA-256 is recorded, in a version that is recorded;
5. a full copy went to the same address straight after, and nobody objected.

Link 5 is the strongest in practice: a confirmation the owner received and kept, of a contract they then used for months.

**What the record should not keep**, under Ley 19.628 art. 3 c) ("limitarse estrictamente a aquéllos que resulten necesarios, adecuados y pertinentes"): the link or code itself, or a hash that could replay it; a browser fingerprint; a location; the owner's RUT or ID number (the law asks none, and #499 has no need of it); the email's body beyond what step 5 sent. The IP address and user agent are personal data with a modest use: they show the acceptance came from the same kind of device and network as the owner's other use, and they are what an expert would ask for under art. 348 bis. Keep them on the acceptance row only, not on every sign-in: one record per act, for that act's proof.

How long: the contract's life, then five years, the ordinary civil action (Código Civil art. 2515, as in [question 7](#7-accounting-retention)). Rakin's own privacy notice today keeps an administrator's data "12 meses después" and says its logs keep no IP addresses, so it needs one line for this record (requirement 16 below).

**Proposed decision.** Email sign-in is enough to form the contract. The record keeps the list in [requirements](#requirements-for-499), including IP and user agent for the acceptance alone, for the contract's life plus five years.

**Confidence:** reasonable (no case law either way; the general rules make it a question of evidence). **Needs the lawyer:** no.

### 3. The processor contract under Ley 21.719

**Answer.** Ley 19.628 art. 15 bis, inciso 3, as Ley 21.719 writes it:

> "El tratamiento de datos a través de un tercero mandatario o encargado se regirá por el contrato celebrado entre el responsable y el encargado, con arreglo a la legislación vigente. En el contrato se deberá establecer el objeto del encargo, la duración del mismo, la finalidad del tratamiento, el tipo de datos personales tratados, las categorías de titulares a quienes conciernen los datos, y los derechos y obligaciones de las partes. El encargado no podrá delegar parte o la totalidad del encargo, salvo que conste una autorización específica y por escrito del responsable. [...] La Agencia pondrá a disposición del público modelos tipo de contratos en su página web."

Three points:

- **The contract itself has no prescribed form.** The article asks for a contract and its contents, not that it be written. The Términos de encargo already carry each listed content (clauses 1 to 4 and those after).
- **The authorisation to subcontract must be written and specific.** Art. 3 of Ley 19.799 makes an electronically signed act "escrito" exactly "en los casos en que la ley exija que los mismos consten de ese modo". So an acceptance in the app can be that authorisation, as long as it is *specific*: the page shows Anexo A, with every subprocessor by name, before the checkbox, and the checkbox's words say it authorises them.
- **Elsewhere the same law accepts electronic means outright:** a *cesión* "deberá constar por escrito o a través de cualquier medio electrónico idóneo" (art. 15). That is a different act, but it shows the law does not read "written" as "paper".

The Agencia has published no model contract (it has no council yet, [question 4](#4-effective-date)).

**Proposed decision.** The acceptance concludes the Términos de encargo and gives the subprocessors' authorisation, provided Anexo A is on the page and named in the checkbox. Clause 9 and Anexo A say "con la firma de este contrato"; they should say "aceptación" ([question 5](#5-a-line-in-the-texts)).

**Confidence:** reasonable (no case law or Agencia guidance yet). **Needs the lawyer:** yes, item A.

### 4. The consumer law

**Answer.** Three steps.

**Today, no.** A *consumidor* acquires a service "en virtud de cualquier acto jurídico oneroso" (Ley 19.496 art. 1, 1), and a *proveedor* provides services "por las que se cobre precio o tarifa" (art. 1, 2). During the free beta (Términos de servicio, section 2) there is no price, so neither the consumer law nor Ley 20.416's extension of it applies.

**When Rakin charges, yes, for most gyms.** A gym that buys software for its business is not obviously a consumer: art. 1, 1 asks that it use the service "como destinatarios finales". But Ley 20.416, art. 9 (*Rol de Consumidoras*), settles it for small businesses, whatever their legal form:

> "Serán aplicables a los actos y contratos celebrados entre micro o pequeñas empresas y sus proveedores las normas establecidas en favor de los consumidores por [...] la ley N° 19.496 en los párrafos 1°, 3°, 4° y 5° del Título II, y en los párrafos 1°, 2°, 3° y 4° del Título III [...]. La aplicación de las disposiciones señaladas precedentemente será irrenunciable anticipadamente por parte de las micro y pequeñas empresas."

A micro company sells up to 2,400 UF a year and a small one up to 25,000 (Ley 20.416 art. 2), so almost every gym is one. Its "proveedores" are defined by art. 1 of Ley 19.496, price included. A sole trader is the same case as a company here: the question is size, not form.

**What it asks, from paragraph 3 of Title II.** Art. 12 A:

> "En los contratos celebrados por medios electrónicos [...] el consentimiento no se entenderá formado si el consumidor no ha tenido previamente un acceso claro, comprensible e inequívoco de las condiciones generales del mismo y la posibilidad de almacenarlos o imprimirlos. [...] Una vez perfeccionado el contrato, el proveedor estará obligado a enviar confirmación escrita del mismo. Ésta podrá ser enviada por vía electrónica [...]. Dicha confirmación deberá contener una copia íntegra, clara y legible del contrato."

Ley 21.398 (2021) did not change art. 12 A. It did rewrite art. 3 bis b), the right to cancel an electronic contract within 10 days: for services, the provider may exclude it, informing "de manera inequívoca, destacada y fácilmente accesible, en forma previa a la suscripción del contrato", and if the art. 12 A confirmation was not sent, the period stretches to 90 days. Art. 3 a) says "El silencio no constituye aceptación en los actos de consumo". Art. 17 asks that adhesion contracts be "claramente legible, con un tamaño de letra no inferior a 2,5 milímetros y en idioma castellano", and that the consumer get a full copy as soon as they sign.

**Proposed decision.** Build art. 12 A now, though it does not bind yet. It is what #499 already plans, made explicit: the full text on the page, with a button to download or print it **before** the checkbox; the box unticked; and a full copy sent to the owner's email once accepted. The rest (cancellation, courts, adhesion clauses) belongs in section 12 of the Términos de servicio, written before Rakin charges.

**Confidence:** clear that it does not apply today; reasonable on what it will require. **Needs the lawyer:** yes, item C, before Rakin charges.

### 5. A line in the texts

**Answer.** The law asks no particular words. But both texts now speak of a signed copy and end in a signature table: the Términos de encargo's version line ("Cada academia firma esta versión [...] y guarda la copia firmada en sus archivos"), its clause 9 and Anexo A ("con la firma de este contrato"), and both "Firmas" tables. After #499 those describe a process that no longer happens. A text that says how it was accepted helps prove that it was.

**Proposed wording.** A clause for both texts, before "Ley y tribunales":

> **Aceptación electrónica.** Estos términos se aceptan en la aplicación de Rakin. Quien los acepta lo hace en nombre de la Academia y declara tener facultades para representarla. Ingresa con un link o código enviado a su correo, revisa el texto, que puede descargar o imprimir antes de aceptar, y marca la casilla de aceptación. Esa aceptación es una firma electrónica según la ley N° 19.799, y obliga a la Academia igual que un contrato firmado en papel. Rakin registra quién aceptó, el correo con que ingresó, la fecha y hora, la versión, una huella (SHA-256) del texto exacto que se mostró y la dirección IP y el navegador desde los que se aceptó. Rakin envía a ese correo una copia íntegra de lo aceptado, y la Academia puede descargarla en cualquier momento desde la administración de su academia.

The "Firmas" table becomes an acceptance block, filled in on the copy the app generates (outside the hashed text, which it describes):

> **Aceptado electrónicamente** por [nombre], en representación de [razón social de la Academia], el [fecha y hora, hora de Chile], con el correo [correo]. Versión [versión]. Huella SHA-256 del texto aceptado: [huella].

And in the Términos de encargo:

- the version line: "Cada academia acepta esta versión en la aplicación antes de que sus datos entren a Rakin, y vuelve a aceptarla cuando cambia [...]. La Empresa registra cada aceptación como dice la cláusula [Aceptación electrónica]."
- clause 9: "con su aceptación de este contrato", for "con la firma de este contrato"; and for a new subprocessor, "una nueva autorización, que la Academia da en la aplicación";
- Anexo A: "La aceptación de este contrato es la autorización específica de cada uno."

These are proposals for the texts' review, not edits: the texts change in #499, with a new version ([question 6](#6-re-accepting-a-new-version)).

**Confidence:** reasonable. **Needs the lawyer:** yes, as part of the texts' review.

### 6. Re-accepting a new version

**Answer.** The law has nothing particular for a second acceptance: it is a new act, made the same way, and everything above applies to it again. Four things differ in practice.

- **Silence is not acceptance.** Ley 19.496 art. 3 a) once it applies, and the general rule meanwhile: a new version binds only when the owner accepts it. Until then the previous one governs. Section 7 of the Términos de servicio already gives 30 days' notice and a right to leave; it should say plainly that the previous version stays in force until the Academia accepts the new one or leaves. A clause letting one party "modificar a su solo arbitrio el contrato" has no effect in an adhesion contract (art. 16 a), so an "accepted by continuing to use it" rule should not be written.
- **A new subprocessor is a new specific authorisation** (art. 15 bis). The page names it, says what it will do and where, and the checkbox authorises it by name. The company does not route a gym's data through it before that gym accepts. Clause 9's right to leave without cost stands.
- **Show what changed.** #499 step 6 shows the changelog. The full new text must still be available to read, save and print before accepting (art. 12 A); a summary of changes is not the contract.
- **The gate must not hold the data hostage.** #499 step 5 limits the titular's admin to the acceptance page until they accept. That is right for data writes. A gym that declines must still be able to take its data and leave (Términos de servicio 4 and 8; Términos de encargo 14), so the export and termination stay open behind the gate.

The record is a new row, with its own hash and copy email; the old row stays, as #499 plans.

**Proposed decision.** The same flow, with the four points above.

**Confidence:** clear. **Needs the lawyer:** no.

### Requirements for #499

What the build needs for the acceptance to hold up, from the answers above. Numbers are for reference from #499's comments.

**The record** (one immutable row per acceptance, per gym and version):

1. The gym, and the person who accepted, by id.
2. The email address of the session that accepted, and the session's sign-in time (`auth_session.created_at`); the email address the operator entered when creating the gym, and which operator entered it.
3. The time of acceptance, from the server, in UTC.
4. Per document: its version, and the SHA-256 of the exact text rendered on the page, blanks filled in. The values the owner filled in (clause 12's contacts), stored as given.
5. The checkboxes' own words, or a version of them, so the record shows what was declared, representation included.
6. The IP address and user agent of the acceptance request. Not on other rows, and not on sign-ins.
7. How it was accepted: `in_app`, or `outside` for `app.gyms sign-terms` and the platform date field (#499 step 7).
8. When the copy email was sent, and its Resend id.
9. Not kept: the link, the code, any hash of them, a browser fingerprint, a location, the owner's RUT.
10. Kept for the contract's life plus five years, then deleted, gym deletion included.

**The page:**

11. Both texts in full, before the checkboxes, with a button to download or print them before accepting. Anexo A with every subprocessor by name.
12. One checkbox per document, unticked, whose words say what they accept. Proposed:
    - "Acepto los Términos de servicio en nombre de [razón social], y declaro que puedo representarla."
    - "Acepto los Términos de encargo en nombre de [razón social], incluida la autorización a cada subencargado del Anexo A."

    The button stays disabled until both are ticked.

**The email** (essential notice, to the address the session signed in with, straight after acceptance):

13. Subject and body in the gym's words: what was accepted, by whom, when, which versions; and a **full copy** of both texts, attached as PDF or HTML, with the acceptance block of [question 5](#5-a-line-in-the-texts). A link alone is not a copy (art. 12 A: "copia íntegra"). Text at a readable size, well above 2.5 mm (art. 17).

**Elsewhere:**

14. The admin's copy download (#499 step 4) gives the same document the email attached.
15. On a new version: requirements 11 to 13 again, with what changed, and a new subprocessor named in the checkbox. The previous version governs until acceptance; data export and termination stay open behind the gate.
16. Rakin's privacy notice (`docs/legal/aviso-de-privacidad-rakin.md`) gets one line: the acceptance record, its IP and user agent, kept for the contract's life plus five years.
17. The texts' changes of [question 5](#5-a-line-in-the-texts) go into a new version of both.

### Sources, for #500

All read on 2026-11-20.

**Primary**

- Ley 19.799, on electronic documents and signatures, version of 2024-02-09 (BCN LeyChile, `idNorma=196640`): <https://www.bcn.cl/leychile/navegar?idNorma=196640>. Arts. 1 to 5 and 12 read through LeyChile's XML service: <https://www.leychile.cl/Consulta/obtxml?opt=7&idNorma=196640>
- Ley 19.496, on consumer protection (BCN LeyChile, `idNorma=61438`), arts. 1, 2, 3, 3 bis, 12 A, 16 and 17: <https://www.bcn.cl/leychile/navegar?idNorma=61438>. LeyChile's XML served a version from before Ley 21.398, so art. 3 bis b) is quoted as Ley 21.398 rewrites it.
- Ley 21.398, *Pro Consumidor*, Diario Oficial 24 December 2021, art. 1, nos. 3 and 4: <https://www.diariooficial.interior.gob.cl/publicaciones/2021/12/24/43136/01/2061725.pdf>
- Ley 20.416, arts. 2 and 9 (*Rol de Consumidoras*), version of 2025-09-29 (BCN LeyChile, `idNorma=1010668`): <https://www.bcn.cl/leychile/navegar?idNorma=1010668>
- Ley 19.628 as Ley 21.719 amends it, version of 2026-12-01, arts. 3, 15 and 15 bis: <https://www.bcn.cl/leychile/navegar?idNorma=141599&idVersion=2026-12-01>
- Código Civil, arts. 1448, 1708, 1709, 1711 and 2515 (BCN LeyChile, `idNorma=172986`): <https://www.bcn.cl/leychile/navegar?idNorma=172986>
- Código de Procedimiento Civil, art. 348 bis (BCN LeyChile, `idNorma=22740`): <https://www.bcn.cl/leychile/navegar?idNorma=22740>

**Not found.** No ruling of the Corte Suprema or of a Corte de Apelaciones on whether email sign-in identifies the author of a simple electronic signature. Searches turned up a 2007 Corte Suprema ruling (rol 3169-2005) cited in a law journal's footnote without its holding, and blogs citing rulings without a rol; neither is used here. No act of the Subsecretaría de Economía on simple signatures, and nothing from the Agencia. The regulation of Ley 19.799 (Decreto 181 of 2002) was not read: LeyChile refused it, and it governs certification providers, not simple signatures.

**Secondary, used only to find the primary texts**

- Revista Actualidad Jurídica N° 29, Universidad del Desarrollo, January 2014: <https://derecho.udd.cl/actualidad-juridica/files/2021/01/AJ29_613.pdf>
